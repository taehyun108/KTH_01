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
import uuid
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

logger = logging.getLogger("p-agent.runtime")

#: 현재 실행 중인 run_id (승인 콜백에서 실행을 식별하기 위해 사용)
current_run_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_run_id", default=""
)

#: 사용자 승인 대기 제한 시간(초). 초과 시 자동 거절한다.
APPROVAL_TIMEOUT: float = 300.0

#: 도구 결과 요약을 자를 길이
SUMMARY_LIMIT: int = 500


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
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[AgentEvent]]] = {}
        self._history: dict[str, list[AgentEvent]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue[AgentEvent]:
        """실행 이벤트를 구독한다. (이미 발생한 이벤트도 큐에 먼저 채워준다)"""
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        for event in self._history.get(run_id, []):
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
        self._history.setdefault(event.run_id, []).append(event)
        for queue in list(self._subscribers.get(event.run_id, [])):
            await queue.put(event)

    def history(self, run_id: str) -> list[AgentEvent]:
        """해당 실행의 전체 이벤트 기록."""
        return list(self._history.get(run_id, []))

    def clear(self, run_id: str) -> None:
        """실행 기록을 정리한다."""
        self._history.pop(run_id, None)
        self._subscribers.pop(run_id, None)


@dataclass
class PendingApproval:
    """사용자 승인을 기다리는 요청."""

    approval_id: str
    run_id: str
    tool_display: str
    arguments: dict[str, Any]
    future: asyncio.Future[bool]


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
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.event_bus = event_bus or EventBus()
        self.settings = settings or get_settings()

        self._kill_events: dict[str, asyncio.Event] = {}
        self._approvals: dict[str, PendingApproval] = {}

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
        # 대기 중인 승인 요청도 모두 거절 처리한다.
        for approval in list(self._approvals.values()):
            if approval.run_id == run_id and not approval.future.done():
                approval.future.set_result(False)
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
        for approval_id, approval in list(self._approvals.items()):
            if approval.run_id == run_id:
                self._approvals.pop(approval_id, None)

    # ------------------------------------------------------------
    # 승인 게이트
    # ------------------------------------------------------------
    @property
    def pending_approvals(self) -> list[PendingApproval]:
        """승인 대기 중인 요청 목록."""
        return list(self._approvals.values())

    def resolve_approval(self, approval_id: str, approved: bool) -> bool:
        """
        승인/거절 결과를 반영한다. (`/api/agent/approve` 에서 호출)

        Returns:
            처리되었으면 True, 없는 요청이면 False
        """
        approval = self._approvals.pop(approval_id, None)
        if approval is None or approval.future.done():
            return False
        approval.future.set_result(approved)
        return True

    async def _on_approval_required(
        self, tool: RegisteredTool, arguments: dict[str, Any]
    ) -> bool:
        """
        ToolRegistry 가 위험 도구 실행 전에 호출하는 승인 콜백.

        프론트엔드에 승인 요청 이벤트를 보내고 응답을 기다린다.
        제한 시간을 넘기면 **자동 거절**한다. (안전 우선)
        """
        run_id = current_run_id.get()
        approval_id = uuid.uuid4().hex[:12]
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()

        approval = PendingApproval(
            approval_id=approval_id,
            run_id=run_id,
            tool_display=tool.display_name,
            arguments=arguments,
            future=future,
        )
        self._approvals[approval_id] = approval

        await self.emit(
            run_id,
            "approval_required",
            approval_id=approval_id,
            tool=tool.display_name,
            arguments=arguments,
        )

        try:
            approved = await asyncio.wait_for(future, timeout=APPROVAL_TIMEOUT)
        except TimeoutError:
            approved = False
            await self.emit(
                run_id,
                "approval_timeout",
                approval_id=approval_id,
                tool=tool.display_name,
            )
        finally:
            self._approvals.pop(approval_id, None)

        await self.emit(
            run_id,
            "approval_resolved",
            approval_id=approval_id,
            tool=tool.display_name,
            approved=approved,
        )
        return approved

    async def _on_action_logged(
        self,
        tool: RegisteredTool,
        arguments: dict[str, Any],
        output: str,
        ok: bool,
    ) -> None:
        """
        도구 실행 기록 콜백.

        STEP 5 에서 여기에 `./logs/actions.jsonl` 파일 기록을 추가한다.
        """
        logger.info(
            "도구 실행 %s %s -> %s",
            tool.display_name,
            arguments,
            "성공" if ok else "실패",
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

        try:
            tool = self.registry.get(qualified_name)
            display = tool.display_name
        except Exception:  # noqa: BLE001 - 없는 도구도 기록만 남기고 진행
            display = qualified_name

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

    def has_tool(self, qualified_name: str) -> bool:
        """해당 도구가 등록되어 있는지 확인한다."""
        try:
            self.registry.get(qualified_name)
        except Exception:  # noqa: BLE001
            return False
        return True
