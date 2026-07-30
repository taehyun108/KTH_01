"""
Agent 실행 런타임.

6개 Agent 가 공유하는 실행 컨텍스트를 제공한다.

  - LLM 클라이언트 (LLMClient.from_env() 로만 생성)
  - MCP 도구 레지스트리 (Agent 는 이걸 통해서만 도구 호출)
  - 이벤트 버스 (WebSocket 실시간 전송용)
  - Kill Switch (실행 중단)
  - 승인 브로커 (위험 도구 실행 전 사용자 승인 대기)

⚠️ 현재 실행 중인 run_id 는 `contextvars` 로 전달한다.
   MCP 레지스트리의 승인 콜백 시그니처가 (도구, 인자) 뿐이라
   어느 실행에서 온 요청인지 알아야 하기 때문이다.

STEP 5 연계
-----------
Kill Switch 의 **전역 키보드 훅(ESC)** 과 **Undo/Action Logger 파일 기록**은
STEP 5 에서 이 런타임에 연결한다. 여기서는 API/그래프가 쓰는 최소 기능만 제공한다.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config.settings import Settings, get_settings
from app.llm.base import BaseLLMClient
from app.llm.factory import LLMClient
from app.mcp_client.client import MCPClient
from app.mcp_client.tool_registry import (
    ApprovalDeniedError,
    RegisteredTool,
    ToolRegistry,
)
from app.safety.action_logger import ActionLogger, ActionRecord
from app.safety.approval_gate import ApprovalGate, PendingApproval
from app.safety.undo_manager import UndoManager, make_file_undo_action

logger = logging.getLogger("pfm-agent.runtime")

#: 현재 실행 중인 run_id (승인 콜백에서 실행을 식별하기 위해 사용)
current_run_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_run_id", default=""
)

#: 현재 실행 중인 Agent 단계 (액션 기록에 남긴다)
current_step: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_step", default=""
)

#: 사용자 승인 대기 제한 시간(초). 초과 시 자동 거절한다.
APPROVAL_TIMEOUT: float = 300.0

#: 도구 결과 요약을 자를 길이
SUMMARY_LIMIT: int = 500

#: 실행 1건당 보관하는 이벤트 최대 개수. (넘으면 오래된 것부터 버린다)
MAX_EVENTS_PER_RUN: int = 2000

#: 이벤트 기록을 보관하는 실행 최대 개수. (앱을 켜 둔 채 요청을 계속 넣는 경우 대비)
MAX_TRACKED_RUNS: int = 50


def _now() -> str:
    """ISO 8601 UTC 타임스탬프."""
    return datetime.now(UTC).isoformat()


class KilledError(RuntimeError):
    """Kill Switch 로 실행이 중단된 경우."""


@dataclass
class AgentEvent:
    """프론트엔드로 전송되는 실시간 이벤트."""

    run_id: str
    type: str
    """이벤트 종류 (run_started / step_started / tool_call / approval_required / ...)"""

    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        """WebSocket 전송용 dict."""
        return {
            "run_id": self.run_id,
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class EventBus:
    """
    실행별 이벤트를 구독자(WebSocket)에게 전달하는 간단한 버스.

    구독자가 없어도 이벤트는 버려질 뿐 실행에는 영향이 없다.

    ⚡ 메모리 상한
    ------------
    회사 PC 에서 앱을 켜 둔 채 요청을 계속 넣으면 기록이 무한히 쌓여
    메모리를 잠식한다. 그래서 두 가지 상한을 둔다.

    - 실행 1건당 이벤트 수: `max_events_per_run` (넘으면 오래된 것부터 버림)
    - 보관하는 실행 수:     `max_runs` (넘으면 가장 오래된 실행 기록을 버림)
    """

    def __init__(
        self,
        *,
        max_events_per_run: int = MAX_EVENTS_PER_RUN,
        max_runs: int = MAX_TRACKED_RUNS,
    ) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[AgentEvent]]] = {}
        # dict 는 삽입 순서를 유지하므로 가장 앞이 가장 오래된 실행이다.
        self._history: dict[str, deque[AgentEvent]] = {}
        self._max_events_per_run = max(1, max_events_per_run)
        self._max_runs = max(1, max_runs)

    def subscribe(self, run_id: str) -> asyncio.Queue[AgentEvent]:
        """실행 이벤트를 구독한다. (이미 발생한 이벤트도 큐에 먼저 채워준다)"""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        for event in self._history.get(run_id, ()):
            queue.put_nowait(event)
        self._subscribers.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[AgentEvent]) -> None:
        """구독을 해제한다."""
        subscribers = self._subscribers.get(run_id)
        if subscribers and queue in subscribers:
            subscribers.remove(queue)

    async def publish(self, event: AgentEvent) -> None:
        """이벤트를 모든 구독자에게 전달하고 기록에 남긴다."""
        history = self._history.get(event.run_id)
        if history is None:
            # deque(maxlen=...) 이 오래된 이벤트를 자동으로 밀어낸다.
            history = deque(maxlen=self._max_events_per_run)
            self._history[event.run_id] = history
            self._evict_old_runs()
        history.append(event)

        for queue in list(self._subscribers.get(event.run_id, [])):
            await queue.put(event)

    def _evict_old_runs(self) -> None:
        """보관 실행 수 상한을 넘으면 가장 오래된 실행 기록을 버린다."""
        while len(self._history) > self._max_runs:
            oldest = next(iter(self._history))
            self._history.pop(oldest, None)
            # 구독자가 남아 있는 실행은 구독 목록을 건드리지 않는다.
            # (WebSocket 이 끊길 때 unsubscribe 로 정리된다)

    def history(self, run_id: str) -> list[AgentEvent]:
        """해당 실행의 이벤트 기록. (상한을 넘긴 오래된 이벤트는 제외)"""
        return list(self._history.get(run_id, ()))

    def clear(self, run_id: str) -> None:
        """실행 기록을 정리한다."""
        self._history.pop(run_id, None)
        self._subscribers.pop(run_id, None)

    @property
    def tracked_runs(self) -> int:
        """기록을 보관 중인 실행 수. (메모리 상한 확인용)"""
        return len(self._history)


class AgentRuntime:
    """
    Agent 실행에 필요한 모든 자원을 묶은 런타임.

    Example:
        runtime = AgentRuntime(llm=LLMClient.from_env(), registry=registry)
        result = await runtime.call_tool("planner", "filesystem__list_dir", {"path": "."})
    """

    def __init__(
        self,
        *,
        llm: BaseLLMClient,
        registry: ToolRegistry,
        event_bus: EventBus | None = None,
        settings: Settings | None = None,
        approval_gate: ApprovalGate | None = None,
        undo_manager: UndoManager | None = None,
        action_logger: ActionLogger | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.event_bus = event_bus or EventBus()
        self.settings = settings or get_settings()

        self._kill_events: dict[str, asyncio.Event] = {}

        # 컴파일된 LangGraph 캐시. (`app.agents.graph.get_graph()` 가 채운다)
        # 그래프 구조는 런타임마다 고정이므로 실행마다 재컴파일할 이유가 없다.
        # graph.py 가 runtime.py 를 import 하므로 반대 방향 import 를 피하려고
        # 타입을 Any 로 두고 이 자리에만 보관한다.
        self.compiled_graph: Any = None

        # --- 안전장치 (STEP 5) ---
        self.approval_gate = approval_gate or ApprovalGate(
            emit=self.emit, timeout=APPROVAL_TIMEOUT
        )
        self.undo_manager = undo_manager or UndoManager()
        self.action_logger = action_logger or ActionLogger(
            self.settings.action_log_path
        )

        # 레지스트리에 승인/기록 콜백을 연결한다.
        registry.approval_callback = self._on_approval_required
        registry.action_log_callback = self._on_action_logged

    # ------------------------------------------------------------
    # 생성 헬퍼
    # ------------------------------------------------------------
    @classmethod
    def create(
        cls,
        mcp_client: MCPClient,
        *,
        event_bus: EventBus | None = None,
        settings: Settings | None = None,
        llm: BaseLLMClient | None = None,
    ) -> AgentRuntime:
        """
        연결된 MCP 클라이언트로부터 런타임을 만든다.

        Args:
            mcp_client: 이미 connect() 된 MCPClient
            llm: 테스트용 LLM 주입. 생략 시 `.env` 설정으로 생성한다.
        """
        resolved_settings = settings or get_settings()
        registry = ToolRegistry(
            mcp_client, require_approval=resolved_settings.require_approval
        )
        registry.refresh()
        return cls(
            llm=llm or LLMClient.from_env(resolved_settings),
            registry=registry,
            event_bus=event_bus,
            settings=resolved_settings,
        )

    # ------------------------------------------------------------
    # 이벤트
    # ------------------------------------------------------------
    async def emit(self, run_id: str, event_type: str, **payload: Any) -> None:
        """이벤트를 발행한다."""
        await self.event_bus.publish(
            AgentEvent(run_id=run_id, type=event_type, payload=payload)
        )

    # ------------------------------------------------------------
    # Kill Switch
    # ------------------------------------------------------------
    def register_run(self, run_id: str) -> None:
        """새 실행을 등록한다."""
        self._kill_events[run_id] = asyncio.Event()

    def kill(self, run_id: str) -> bool:
        """
        실행 중단을 요청한다.

        Returns:
            중단 신호를 보냈으면 True, 없는 실행이면 False
        """
        event = self._kill_events.get(run_id)
        if event is None:
            return False
        event.set()
        # 대기 중인 승인 요청도 모두 거절 처리한다. (무단 실행 방지)
        denied = self.approval_gate.deny_all_for_run(run_id)
        if denied:
            logger.info("중단으로 승인 요청 %d건을 거절했습니다", denied)
        return True

    def is_killed(self, run_id: str) -> bool:
        """중단 요청이 있었는지 확인한다."""
        event = self._kill_events.get(run_id)
        return bool(event and event.is_set())

    def ensure_alive(self, run_id: str) -> None:
        """중단되었으면 예외를 던진다. (각 노드 시작 시 호출)"""
        if self.is_killed(run_id):
            raise KilledError("사용자가 실행을 중단했습니다.")

    def cleanup_run(self, run_id: str) -> None:
        """실행 관련 자원을 정리한다."""
        self._kill_events.pop(run_id, None)
        self.approval_gate.clear_run(run_id)

    # ------------------------------------------------------------
    # 승인 게이트 (app/safety/approval_gate.py 로 위임)
    # ------------------------------------------------------------
    @property
    def pending_approvals(self) -> list[PendingApproval]:
        """승인 대기 중인 요청 목록."""
        return self.approval_gate.pending

    def resolve_approval(self, approval_id: str, approved: bool) -> bool:
        """
        승인/거절 결과를 반영한다. (`/api/agent/approve` 에서 호출)

        Returns:
            처리되었으면 True, 없는 요청이면 False
        """
        return self.approval_gate.resolve(approval_id, approved)

    async def _on_approval_required(
        self, tool: RegisteredTool, arguments: dict[str, Any]
    ) -> bool:
        """ToolRegistry 가 위험 도구 실행 전에 호출하는 승인 콜백."""
        run_id = current_run_id.get()
        return await self.approval_gate.request(run_id, tool.display_name, arguments)

    async def _on_action_logged(
        self,
        tool: RegisteredTool,
        arguments: dict[str, Any],
        output: str,
        ok: bool,
    ) -> None:
        """
        도구 실행 기록 콜백.

        모든 도구 실행을 `./logs/actions.jsonl` 에 남긴다.
        """
        logger.info(
            "도구 실행 %s %s -> %s",
            tool.display_name,
            arguments,
            "성공" if ok else "실패",
        )
        await self.action_logger.log(
            ActionRecord(
                run_id=current_run_id.get(),
                step=current_step.get(),
                action="tool_call",
                tool=tool.display_name,
                arguments=arguments,
                ok=ok,
                detail=output[:SUMMARY_LIMIT],
            )
        )

    # ------------------------------------------------------------
    # 도구 호출 (Agent 는 반드시 이 메서드를 사용한다)
    # ------------------------------------------------------------
    async def call_tool(
        self,
        step: str,
        qualified_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        run_id: str = "",
    ) -> dict[str, Any]:
        """
        MCP 도구를 실행하고 결과를 기록 형태로 반환한다.

        ⚠️ Agent 는 절대 도구 함수를 직접 호출하지 않고 이 메서드만 사용한다.

        Returns:
            {"ok": bool, "text": str, "structured": dict|None, "log": ToolLogEntry}
            (도구가 실패해도 예외를 던지지 않는다. 그래프가 멈추지 않도록 하기 위함)
        """
        active_run = run_id or current_run_id.get()
        args = arguments or {}
        current_step.set(step)

        try:
            tool = self.registry.get(qualified_name)
            display = tool.display_name
        except Exception:  # noqa: BLE001 - 없는 도구도 기록만 남기고 진행
            display = qualified_name

        # 되돌릴 수 있는 액션이면 실행 **전에** 현재 상태를 저장해 둔다.
        undo_snapshot = self._snapshot_for_undo(qualified_name, args)

        await self.emit(
            active_run, "tool_call", step=step, tool=display, arguments=args
        )

        ok = True
        text = ""
        structured: dict[str, Any] | None = None

        try:
            result = await self.registry.call(qualified_name, args)
            ok = not result.is_error
            text = result.text
            structured = result.structured
        except ApprovalDeniedError as exc:
            ok = False
            text = str(exc)
        except Exception as exc:  # noqa: BLE001 - 도구 실패로 그래프를 멈추지 않는다
            ok = False
            text = str(exc)

        # 성공한 경우에만 되돌리기 스택에 올린다.
        if ok and undo_snapshot is not None:
            self.undo_manager.push(undo_snapshot(active_run))

        summary = text if len(text) <= SUMMARY_LIMIT else text[:SUMMARY_LIMIT] + "…"
        log_entry = {
            "step": step,
            "tool": display,
            "arguments": args,
            "ok": ok,
            "summary": summary,
        }

        await self.emit(
            active_run,
            "tool_result",
            step=step,
            tool=display,
            ok=ok,
            summary=summary,
        )

        return {"ok": ok, "text": text, "structured": structured, "log": log_entry}

    def _snapshot_for_undo(
        self, qualified_name: str, arguments: dict[str, Any]
    ) -> Any:
        """
        되돌리기용 스냅샷을 만든다.

        현재는 파일 쓰기만 되돌릴 수 있다.
        (마우스 클릭·키 입력은 되돌릴 수 없으므로 스택에 넣지 않는다)

        Returns:
            run_id 를 받아 UndoAction 을 만드는 함수, 되돌릴 수 없으면 None
        """
        if qualified_name != "filesystem__write_file":
            return None

        raw_path = arguments.get("path")
        if not raw_path:
            return None

        try:
            from app.mcp_servers.base_server import safe_project_path

            target = safe_project_path(str(raw_path))
        except Exception:  # noqa: BLE001 - 경로가 잘못되면 되돌리기 대상이 아니다
            return None

        previous = None
        if target.is_file():
            try:
                previous = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # 읽을 수 없는 파일은 되돌리기를 제공하지 않는다.
                return None

        def _make(active_run: str) -> Any:
            return make_file_undo_action(target, previous, run_id=active_run)

        return _make

    async def undo_last(self, run_id: str = "") -> str:
        """
        가장 최근 액션을 되돌린다.

        Returns:
            되돌린 액션 설명

        Raises:
            UndoError: 되돌릴 것이 없거나 실패한 경우
        """
        description = await self.undo_manager.undo_last()
        await self.action_logger.log(
            ActionRecord(
                run_id=run_id,
                step="undo",
                action="undo",
                detail=description,
                ok=True,
            )
        )
        await self.emit(run_id, "undo_performed", description=description)
        return description

    def has_tool(self, qualified_name: str) -> bool:
        """해당 도구가 등록되어 있는지 확인한다."""
        try:
            self.registry.get(qualified_name)
        except Exception:  # noqa: BLE001
            return False
        return True
