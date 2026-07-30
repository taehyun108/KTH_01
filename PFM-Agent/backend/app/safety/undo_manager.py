"""
Undo Manager — 되돌리기 스택.

에이전트가 수행한 되돌릴 수 있는 액션을 스택에 쌓고,
사용자가 요청하면 최근 것부터 취소한다.

되돌릴 수 있는 것 / 없는 것
---------------------------
✅ 파일 쓰기  : 이전 내용을 복원 (새로 만든 파일이면 삭제)
❌ 마우스 클릭 : 이미 발생한 클릭은 되돌릴 수 없음
❌ 키 입력    : 마찬가지

되돌릴 수 없는 액션은 애초에 스택에 넣지 않는다.
"되돌릴 수 있다"고 잘못 안내하는 것이 더 위험하기 때문이다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("pfm-agent.undo")

#: 스택에 보관할 최대 액션 수 (메모리 보호)
MAX_STACK_SIZE: int = 50


class UndoError(RuntimeError):
    """되돌리기 실패. 메시지는 사용자에게 노출되므로 한글로 작성한다."""


@dataclass
class UndoAction:
    """되돌릴 수 있는 액션 한 건."""

    description: str
    """사용자에게 보여줄 설명 (예: "파일 저장: output/보고서.md")"""

    undo: Callable[[], Awaitable[None]]
    """실제 되돌리기를 수행하는 코루틴 함수"""

    run_id: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """API 응답용 dict."""
        return {
            "description": self.description,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }


class UndoManager:
    """
    되돌리기 스택 관리자.

    Example:
        manager = UndoManager()
        manager.push(make_file_undo_action(path, previous_content))
        description = await manager.undo_last()
    """

    def __init__(self, *, max_size: int = MAX_STACK_SIZE) -> None:
        self.max_size = max_size
        self._stack: list[UndoAction] = []

    # ------------------------------------------------------------
    # 스택 조작
    # ------------------------------------------------------------
    def push(self, action: UndoAction) -> None:
        """되돌리기 액션을 스택에 추가한다."""
        self._stack.append(action)
        if len(self._stack) > self.max_size:
            # 오래된 것부터 버린다.
            self._stack.pop(0)

    @property
    def can_undo(self) -> bool:
        """되돌릴 액션이 있는지 여부."""
        return bool(self._stack)

    @property
    def size(self) -> int:
        """스택에 쌓인 액션 수."""
        return len(self._stack)

    def peek(self) -> UndoAction | None:
        """다음에 되돌릴 액션 (실행하지는 않음)."""
        return self._stack[-1] if self._stack else None

    def list_actions(self) -> list[dict[str, Any]]:
        """스택 내용을 최신순으로 반환한다. (UI 표시용)"""
        return [action.to_dict() for action in reversed(self._stack)]

    def clear(self) -> None:
        """스택을 비운다."""
        self._stack.clear()

    # ------------------------------------------------------------
    # 되돌리기
    # ------------------------------------------------------------
    async def undo_last(self) -> str:
        """
        가장 최근 액션을 되돌린다.

        Returns:
            되돌린 액션 설명

        Raises:
            UndoError: 되돌릴 것이 없거나 되돌리기에 실패한 경우
        """
        if not self._stack:
            raise UndoError("되돌릴 작업이 없습니다.")

        action = self._stack.pop()
        try:
            await action.undo()
        except Exception as exc:
            # 실패한 액션은 다시 넣지 않는다. (무한 재시도 방지)
            raise UndoError(
                f"'{action.description}' 되돌리기에 실패했습니다: {exc}"
            ) from exc

        logger.info("되돌리기 완료: %s", action.description)
        return action.description


def make_file_undo_action(
    path: Path, previous_content: str | None, *, run_id: str = ""
) -> UndoAction:
    """
    파일 쓰기에 대한 되돌리기 액션을 만든다.

    Args:
        path: 변경된 파일의 실제 경로
        previous_content: 변경 전 내용. None 이면 새로 만든 파일이므로 삭제한다.
        run_id: 실행 식별자

    Returns:
        UndoAction
    """
    display = path.name

    async def _undo() -> None:
        if previous_content is None:
            # 새로 만든 파일 → 삭제
            path.unlink(missing_ok=True)
        else:
            # 기존 파일 → 이전 내용 복원
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(previous_content, encoding="utf-8")

    verb = "생성" if previous_content is None else "수정"
    return UndoAction(
        description=f"파일 {verb}: {display}",
        undo=_undo,
        run_id=run_id,
    )
