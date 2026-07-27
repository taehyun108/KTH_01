"""
Agent 실행 관리자.

사용자 요청 하나를 "실행(run)" 단위로 관리한다.
  - 실행 시작 / 상태 조회 / 중단 / 승인 응답
  - 실행은 백그라운드 task 로 돌고, 진행 상황은 이벤트 버스로 전달된다.

FastAPI 엔드포인트(`/api/agent/*`)가 이 클래스를 통해 그래프를 구동한다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.agents.graph import run_graph
from app.agents.runtime import AgentRuntime, current_run_id
from app.agents.state import AgentState, initial_state

logger = logging.getLogger("p-agent.run_manager")

#: 실행 상태
RunStatus = Literal["running", "completed", "killed", "error"]


def _now() -> str:
    """ISO 8601 UTC 타임스탬프."""
    return datetime.now(UTC).isoformat()


@dataclass
class RunRecord:
    """실행 한 건의 기록."""

    run_id: str
    user_request: str
    status: RunStatus = "running"
    started_at: str = field(default_factory=_now)
    finished_at: str = ""
    state: AgentState | None = None
    task: asyncio.Task[Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """API 응답용 dict."""
        state = self.state or {}
        return {
            "run_id": self.run_id,
            "user_request": self.user_request,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "plan": state.get("plan", []),
            "confidence": state.get("confidence", 0),
            "verification": state.get("verification", ""),
            "report_path": state.get("report_path", ""),
            "summary": state.get("summary", ""),
            "notes": state.get("notes", []),
            "tool_log": state.get("tool_log", []),
            "error": state.get("error", ""),
        }


class RunManager:
    """Agent 실행을 생성하고 추적한다."""

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime
        self._runs: dict[str, RunRecord] = {}

    # ------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------
    def start(self, user_request: str) -> RunRecord:
        """
        새 실행을 시작한다. (즉시 반환하고 백그라운드에서 진행)

        Args:
            user_request: 사용자가 입력한 자연어 요청

        Returns:
            생성된 실행 기록
        """
        run_id = uuid.uuid4().hex[:12]
        record = RunRecord(run_id=run_id, user_request=user_request)
        self._runs[run_id] = record

        self.runtime.register_run(run_id)
        record.task = asyncio.create_task(
            self._execute(record), name=f"agent-run-{run_id}"
        )
        return record

    async def _execute(self, record: RunRecord) -> None:
        """그래프를 실행하고 결과를 기록한다."""
        run_id = record.run_id
        # 승인 콜백이 어느 실행인지 알 수 있도록 컨텍스트에 심는다.
        current_run_id.set(run_id)

        await self.runtime.emit(
            run_id, "run_started", user_request=record.user_request
        )

        try:
            state = initial_state(run_id, record.user_request)
            result = await run_graph(self.runtime, state)
            record.state = result

            reason = result.get("finish_reason", "completed")
            if reason == "killed":
                record.status = "killed"
            elif reason == "error":
                record.status = "error"
            else:
                record.status = "completed"

        except asyncio.CancelledError:
            record.status = "killed"
            await self.runtime.emit(run_id, "run_killed", reason="취소됨")
            raise
        except Exception as exc:
            logger.exception("실행 중 예기치 못한 오류: %s", run_id)
            record.status = "error"
            record.state = AgentState(
                run_id=run_id,
                error=f"실행 중 오류가 발생했습니다: {exc}",
                notes=[str(exc)],
            )
        finally:
            record.finished_at = _now()
            await self.runtime.emit(
                run_id,
                "run_finished",
                status=record.status,
                summary=(record.state or {}).get("summary", ""),
                report_path=(record.state or {}).get("report_path", ""),
            )
            self.runtime.cleanup_run(run_id)

    # ------------------------------------------------------------
    # 조회 / 제어
    # ------------------------------------------------------------
    def get(self, run_id: str) -> RunRecord | None:
        """실행 기록을 조회한다."""
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunRecord]:
        """모든 실행 기록 (최신순)."""
        return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)

    def kill(self, run_id: str) -> bool:
        """
        실행 중단을 요청한다.

        이미 끝난 실행에 대한 중단 요청은 **성공으로 처리**한다.
        (사용자 입장에서는 "멈춰달라"는 요청이 이미 달성된 상태이므로,
         '실행을 찾을 수 없습니다' 같은 오류를 보여주면 혼란스럽다)

        Returns:
            해당 실행이 존재하면 True, 아예 없는 실행이면 False
        """
        record = self._runs.get(run_id)
        if record is None:
            return False
        if record.status != "running":
            return True  # 이미 종료됨 — 멱등 처리
        self.runtime.kill(run_id)
        return True

    def kill_all(self) -> int:
        """진행 중인 모든 실행을 중단한다. (전역 Kill Switch / ESC 용)"""
        count = 0
        for record in self._runs.values():
            if record.status == "running" and self.runtime.kill(record.run_id):
                count += 1
        return count

    def approve(self, approval_id: str, approved: bool) -> bool:
        """
        승인 요청에 응답한다.

        Returns:
            처리되었으면 True, 없는 요청이면 False
        """
        return self.runtime.resolve_approval(approval_id, approved)

    async def shutdown(self) -> None:
        """진행 중인 실행을 정리한다. (서버 종료 시)"""
        self.kill_all()
        tasks = [r.task for r in self._runs.values() if r.task and not r.task.done()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass  # 종료 시 취소는 정상 경로
            except Exception as exc:  # noqa: BLE001 - 종료 중 오류는 치명적이지 않다
                logger.debug("실행 종료 중 오류: %s", exc)
