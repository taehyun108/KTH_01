"""
MCP 도구 레지스트리.

모든 MCP 서버의 도구를 한데 모아 **LLM/LangGraph 가 쓸 수 있는 형태**로 제공하고,
도구 실행을 중앙에서 통제한다.

책임
----
1. **도구 수집**: 여러 서버의 도구를 모아 하나의 목록으로 제공
2. **이름 충돌 방지**: `서버명__도구명` 으로 정규화
3. **승인 게이트 강제**: `require_approval` 서버의 도구는 승인 없이는 실행 불가
4. **실행 기록**: 모든 도구 호출을 로거로 전달 (STEP 5 Action Logger 연결점)

⚠️ 도구 이름 규칙 (중요)
------------------------
LLM API 의 도구 이름은 `^[a-zA-Z0-9_-]{1,64}$` 만 허용한다.
따라서 **점(.)을 쓸 수 없다.**
  - 내부/LLM 전달용 식별자 : `filesystem__read_file`  (구분자 `__`)
  - 사용자 화면 표시용     : `filesystem.read_file`
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.llm.base import ToolSpec
from app.mcp_client.client import MCPClient, MCPClientError, MCPToolResult

#: LLM 도구 이름에서 서버와 도구를 구분하는 문자열 (점은 사용 불가)
NAME_SEPARATOR = "__"

#: 승인 요청 콜백 타입: (도구, 인자) -> 승인 여부
ApprovalCallback = Callable[["RegisteredTool", dict[str, Any]], Awaitable[bool]]

#: 실행 기록 콜백 타입: (도구, 인자, 결과, 성공여부) -> None
ActionLogCallback = Callable[["RegisteredTool", dict[str, Any], str, bool], Awaitable[None]]


class ApprovalDeniedError(RuntimeError):
    """사용자가 도구 실행을 거절했거나 승인 게이트가 준비되지 않은 경우."""


@dataclass(frozen=True)
class RegisteredTool:
    """레지스트리에 등록된 도구 한 건."""

    server: str
    """소속 MCP 서버 이름 (예: "filesystem")"""

    name: str
    """서버 내 도구 이름 (예: "read_file")"""

    description: str
    input_schema: dict[str, Any]

    require_approval: bool = False
    """실행 전 사용자 승인이 필요한지 여부 (서버 단위 설정)"""

    @property
    def qualified_name(self) -> str:
        """LLM 에 전달하는 고유 이름 (예: filesystem__read_file)."""
        return f"{self.server}{NAME_SEPARATOR}{self.name}"

    @property
    def display_name(self) -> str:
        """사용자 화면에 표시하는 이름 (예: filesystem.read_file)."""
        return f"{self.server}.{self.name}"

    def to_tool_spec(self) -> ToolSpec:
        """LLM Adapter 가 사용하는 ToolSpec 으로 변환한다."""
        description = self.description
        if self.require_approval:
            description = f"{description}\n(주의: 실행 전 사용자 승인이 필요한 도구입니다.)"
        return ToolSpec(
            name=self.qualified_name,
            description=description,
            input_schema=self.input_schema,
        )


def split_qualified_name(qualified_name: str) -> tuple[str, str]:
    """
    `filesystem__read_file` → `("filesystem", "read_file")`

    Raises:
        ValueError: 형식이 잘못된 경우
    """
    if NAME_SEPARATOR not in qualified_name:
        raise ValueError(
            f"도구 이름 형식이 잘못되었습니다: '{qualified_name}' "
            f"(올바른 형식: 서버명{NAME_SEPARATOR}도구명)"
        )
    server, _, tool = qualified_name.partition(NAME_SEPARATOR)
    return server, tool


class ToolRegistry:
    """
    MCP 도구를 모아 LLM/Agent 에 제공하고 실행을 통제하는 레지스트리.

    Example:
        async with MCPClient.from_config() as client:
            registry = ToolRegistry(client, approval_callback=ask_user)
            registry.refresh()

            # LLM 에 넘길 도구 목록
            specs = registry.to_tool_specs()

            # LLM 이 요청한 도구 실행
            result = await registry.call("filesystem__list_dir", {"path": "."})
    """

    def __init__(
        self,
        client: MCPClient,
        *,
        approval_callback: ApprovalCallback | None = None,
        action_log_callback: ActionLogCallback | None = None,
        require_approval: bool = True,
    ) -> None:
        """
        Args:
            client: 연결된 MCPClient
            approval_callback: 승인 요청 콜백. `require_approval` 도구 실행 전 호출된다.
                None 이면 위험 도구 실행이 **차단**된다. (안전 우선 기본값)
            action_log_callback: 실행 기록 콜백 (STEP 5 Action Logger 연결)
            require_approval: 전역 승인 사용 여부. `.env` 의 REQUIRE_APPROVAL 값.
                False 면 승인 게이트를 건너뛴다. (개발 편의용 — 배포 시 true 권장)
        """
        self.client = client
        self.approval_callback = approval_callback
        self.action_log_callback = action_log_callback
        self.require_approval = require_approval
        self._tools: dict[str, RegisteredTool] = {}

    # ------------------------------------------------------------
    # 수집
    # ------------------------------------------------------------
    def refresh(self) -> int:
        """
        연결된 MCP 서버들에서 도구를 다시 수집한다.

        Returns:
            수집된 도구 개수
        """
        self._tools.clear()
        for server_name, tools in self.client.list_tools().items():
            config = self.client.configs.get(server_name)
            needs_approval = bool(config.require_approval) if config else False

            for tool in tools:
                registered = RegisteredTool(
                    server=server_name,
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                    require_approval=needs_approval,
                )
                self._tools[registered.qualified_name] = registered
        return len(self._tools)

    # ------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------
    @property
    def tools(self) -> list[RegisteredTool]:
        """등록된 모든 도구 (이름순)."""
        return sorted(self._tools.values(), key=lambda t: t.qualified_name)

    def get(self, qualified_name: str) -> RegisteredTool:
        """
        정규화된 이름으로 도구를 조회한다.

        Raises:
            MCPClientError: 없는 도구인 경우
        """
        tool = self._tools.get(qualified_name)
        if tool is None:
            available = ", ".join(sorted(self._tools)) or "(없음)"
            raise MCPClientError(
                f"'{qualified_name}' 도구를 찾을 수 없습니다.\n사용 가능한 도구: {available}"
            )
        return tool

    def to_tool_specs(self) -> list[ToolSpec]:
        """LLM 에 전달할 ToolSpec 목록으로 변환한다."""
        return [tool.to_tool_spec() for tool in self.tools]

    def approval_required_tools(self) -> list[RegisteredTool]:
        """승인이 필요한 도구 목록. (UI 안내용)"""
        return [tool for tool in self.tools if tool.require_approval]

    # ------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------
    async def call(
        self, qualified_name: str, arguments: dict[str, Any] | None = None
    ) -> MCPToolResult:
        """
        도구를 실행한다. (승인 게이트 + 실행 기록 포함)

        Args:
            qualified_name: `서버명__도구명`
            arguments: 입력 인자

        Returns:
            MCPToolResult

        Raises:
            MCPClientError: 없는 도구이거나 서버 미연결
            ApprovalDeniedError: 승인이 거절되었거나 승인 게이트가 없는 경우
        """
        tool = self.get(qualified_name)
        args = arguments or {}

        # --- 1) 승인 게이트 ---
        if tool.require_approval and self.require_approval:
            await self._request_approval(tool, args)

        # --- 2) 실행 ---
        result = await self.client.call_tool(tool.server, tool.name, args)

        # --- 3) 실행 기록 ---
        if self.action_log_callback is not None:
            await self.action_log_callback(tool, args, result.text, not result.is_error)

        return result

    async def _request_approval(
        self, tool: RegisteredTool, arguments: dict[str, Any]
    ) -> None:
        """
        승인 게이트를 통과시킨다.

        승인 콜백이 없으면 **차단**한다. (안전 우선 — 무단 실행 방지)
        """
        if self.approval_callback is None:
            raise ApprovalDeniedError(
                f"'{tool.display_name}' 은(는) 사용자 승인이 필요한 도구입니다.\n"
                f"승인 창이 준비되지 않아 실행할 수 없습니다. "
                f"(개발 중이라면 .env 의 REQUIRE_APPROVAL=false 로 임시 해제할 수 있습니다)"
            )

        approved = await self.approval_callback(tool, arguments)
        if not approved:
            raise ApprovalDeniedError(
                f"사용자가 '{tool.display_name}' 실행을 거절했습니다."
            )

    # ------------------------------------------------------------
    # 표시용
    # ------------------------------------------------------------
    def summary(self) -> str:
        """등록 현황을 사람이 읽기 좋은 한글 문자열로 반환한다."""
        if not self._tools:
            return "등록된 MCP 도구가 없습니다."

        lines: list[str] = [f"MCP 도구 {len(self._tools)}개 등록됨"]
        by_server: dict[str, list[RegisteredTool]] = {}
        for tool in self.tools:
            by_server.setdefault(tool.server, []).append(tool)

        for server, tools in sorted(by_server.items()):
            mark = " (승인 필요)" if tools[0].require_approval else ""
            lines.append(f"  {server}{mark}: {len(tools)}개")
            for tool in tools:
                lines.append(f"    - {tool.display_name}")
        return "\n".join(lines)
