"""
Approval Gate — 위험 도구 실행 전 사용자 승인.

Human-in-the-loop 안전장치의 핵심.
`automation` 같은 위험 MCP 서버의 도구는 이 게이트를 통과해야만 실행된다.

동작
----
1. 도구 실행 직전 `request()` 가 호출된다.
2. 프론트엔드에 `approval_required` 이벤트가 전송된다.
3. 사용자가 승인/거절할 때까지 대기한다.
4. 제한 시간(기본 5분)을 넘기면 **자동 거절**한다. (안전 우선)

⚠️ 기본값이 "거절"인 이유
------------------------
사용자가 자리를 비웠거나 창을 못 봤을 때 자동 승인되면,
아무도 모르는 사이에 PC 조작이 일어난다. 그래서 무응답은 거절로 처리한다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("p-agent.approval")

#: 사용자 승인 대기 제한 시간(초). 초과 시 자동 거절한다.
DEFAULT_TIMEOUT: float = 300.0

#: 이벤트 발행 콜백 타입: (run_id, event_type, **payload) -> None
EmitCallback = Callable[..., Awaitable[None]]


@dataclass
class PendingApproval:
    """승인 대기 중인 요청."""

    approval_id: str
    run_id: str
    tool_display: str
    arguments: dict[str, Any]
    future: asyncio.Future[bool]
    requested_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        """API 응답용 dict."""
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "tool": self.tool_display,
            "arguments": self.arguments,
            "requested_at": self.requested_at,
        }


class ApprovalGate:
    """
    승인 게이트.

    Example:
        gate = ApprovalGate(emit=runtime.emit)
        approved = await gate.request(run_id, "automation.click", {"x": 1, "y": 2})
    """

    def __init__(
        self,
        *,
        emit: EmitCallback | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Args:
            emit: 이벤트 발행 함수 (프론트엔드에 승인 요청을 보낸다)
            timeout: 승인 대기 제한 시간(초)
        """
        self.emit = emit
        self.timeout = timeout
        self._pending: dict[str, PendingApproval] = {}

    # ------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------
    @property
    def pending(self) -> list[PendingApproval]:
        """대기 중인 승인 요청 목록."""
        return list(self._pending.values())

    def pending_for_run(self, run_id: str) -> list[PendingApproval]:
        """특정 실행의 대기 중인 요청."""
        return [item for item in self._pending.values() if item.run_id == run_id]

    # ------------------------------------------------------------
    # 요청 / 응답
    # ------------------------------------------------------------
    async def request(
        self, run_id: str, tool_display: str, arguments: dict[str, Any]
    ) -> bool:
        """
        사용자 승인을 요청하고 결과를 기다린다.

        Returns:
            승인되면 True, 거절/시간초과면 False
        """
        approval_id = uuid.uuid4().hex[:12]
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        approval = PendingApproval(
            approval_id=approval_id,
            run_id=run_id,
            tool_display=tool_display,
            arguments=arguments,
            future=future,
        )
        self._pending[approval_id] = approval

        if self.emit is not None:
            await self.emit(
                run_id,
                "approval_required",
                approval_id=approval_id,
                tool=tool_display,
                arguments=arguments,
            )

        logger.info("승인 요청: %s %s", tool_display, arguments)

        try:
            approved = await asyncio.wait_for(future, timeout=self.timeout)
        except TimeoutError:
            approved = False
            logger.warning(
                "승인 시간 초과 → 자동 거절: %s (%.0f초)", tool_display, self.timeout
            )
            if self.emit is not None:
                await self.emit(
                    run_id,
                    "approval_timeout",
                    approval_id=approval_id,
                    tool=tool_display,
                )
        finally:
            self._pending.pop(approval_id, None)

        if self.emit is not None:
            await self.emit(
                run_id,
                "approval_resolved",
                approval_id=approval_id,
                tool=tool_display,
                approved=approved,
            )
        return approved

    def resolve(self, approval_id: str, approved: bool) -> bool:
        """
        승인/거절 결과를 반영한다.

        Returns:
            처리되었으면 True, 없는 요청이면 False
        """
        approval = self._pending.pop(approval_id, None)
        if approval is None or approval.future.done():
            return False
        approval.future.set_result(approved)
        logger.info(
            "승인 %s: %s", "허용" if approved else "거절", approval.tool_display
        )
        return True

    def deny_all_for_run(self, run_id: str) -> int:
        """
        해당 실행의 대기 중인 요청을 모두 거절한다. (Kill Switch 발동 시)

        Returns:
            거절 처리한 요청 수
        """
        count = 0
        for approval in list(self._pending.values()):
            if approval.run_id == run_id and not approval.future.done():
                approval.future.set_result(False)
                self._pending.pop(approval.approval_id, None)
                count += 1
        return count

    def clear_run(self, run_id: str) -> None:
        """실행 종료 시 남은 요청을 정리한다."""
        for approval in list(self._pending.values()):
            if approval.run_id == run_id:
                self._pending.pop(approval.approval_id, None)
