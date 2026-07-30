"""
Action Logger — 모든 액션을 파일에 기록한다.

기록 위치: `./logs/actions.jsonl` (프로젝트 폴더 내부, 포터블 원칙)
형식: 한 줄에 JSON 객체 하나 (JSON Lines)

기록 목적
---------
1. 사고 조사: "에이전트가 무엇을 했는가"를 사후에 확인
2. 사용자 신뢰: 비개발자도 파일을 열어 내역 확인 가능 (한글 기록)
3. 문제 신고: 오류 발생 시 이 파일만 전달하면 원인 파악 가능

한글이 깨지지 않도록 `ensure_ascii=False` + UTF-8 로 기록한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("pfm-agent.action_logger")

#: 로그 파일이 이 크기를 넘으면 회전시킨다. (USB 용량 보호)
MAX_LOG_BYTES: int = 10 * 1024 * 1024  # 10MB

#: 보관할 회전 파일 개수
MAX_BACKUPS: int = 3


def _now() -> str:
    """ISO 8601 UTC 타임스탬프."""
    return datetime.now(UTC).isoformat()


@dataclass
class ActionRecord:
    """기록 한 건."""

    run_id: str
    step: str
    """실행 단계 (planner / executor / ...)"""

    action: str
    """액션 종류 (tool_call / approval / kill / undo ...)"""

    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    detail: str = ""
    timestamp: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화용 dict."""
        return {
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "step": self.step,
            "action": self.action,
            "tool": self.tool,
            "arguments": self.arguments,
            "ok": self.ok,
            "detail": self.detail,
        }


class ActionLogger:
    """
    액션 기록기.

    Example:
        logger = ActionLogger(Path("./logs/actions.jsonl"))
        await logger.log(ActionRecord(run_id="abc", step="executor",
                                      action="tool_call", tool="automation.click"))
    """

    def __init__(self, path: Path, *, max_bytes: int = MAX_LOG_BYTES) -> None:
        """
        Args:
            path: 기록 파일 경로 (프로젝트 폴더 내부여야 함)
            max_bytes: 회전 기준 크기
        """
        self.path = path
        self.max_bytes = max_bytes
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def log(self, record: ActionRecord) -> None:
        """
        기록을 파일에 추가한다.

        기록 실패가 에이전트 실행을 막아서는 안 되므로 예외를 삼키고 경고만 남긴다.
        """
        async with self._lock:
            try:
                self._rotate_if_needed()
                line = json.dumps(record.to_dict(), ensure_ascii=False)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError as exc:  # pragma: no cover - 디스크 문제 등
                logger.warning("액션 기록에 실패했습니다: %s", exc)

    def _rotate_if_needed(self) -> None:
        """파일이 너무 커지면 회전시킨다."""
        if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
            return

        # actions.jsonl.2 -> actions.jsonl.3 ... 순으로 밀어낸다.
        for index in range(MAX_BACKUPS - 1, 0, -1):
            source = self.path.with_suffix(self.path.suffix + f".{index}")
            target = self.path.with_suffix(self.path.suffix + f".{index + 1}")
            if source.exists():
                source.replace(target)

        self.path.replace(self.path.with_suffix(self.path.suffix + ".1"))

    def read_all(self) -> list[dict[str, Any]]:
        """
        기록을 모두 읽는다. (조회 API / 테스트용)

        형식이 깨진 줄은 건너뛴다.
        """
        if not self.path.exists():
            return []

        records: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def read_run(self, run_id: str) -> list[dict[str, Any]]:
        """특정 실행의 기록만 읽는다."""
        return [record for record in self.read_all() if record.get("run_id") == run_id]

    def clear(self) -> None:
        """기록을 비운다. (테스트용)"""
        self.path.unlink(missing_ok=True)
