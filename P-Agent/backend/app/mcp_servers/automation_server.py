"""
automation MCP 서버 — PC 자동화 도구.

제공 도구:
  - click(x, y)        : 마우스 클릭
  - type_text(text)    : 텍스트 입력
  - key_press(key)     : 키 입력
  - open_browser(url)  : 브라우저 열기 (화이트리스트 검사)

🔴 **위험 서버** — mcp_config.json 에서 `require_approval: true` 로 등록된다.
   이 서버의 모든 도구는 실행 전 **Approval Gate(사용자 승인)** 를 반드시 통과해야 하며,
   승인 게이트는 MCP 클라이언트(tool_registry) 레벨에서 강제된다.
   즉, 승인 콜백이 없으면 도구 자체가 호출되지 않는다.

⚠️ 현재 상태: **도구 스키마만 정의된 스텁(stub)**
   실제 구현은 STEP 6 (Perception & Executor) 에서 채운다.
   - PyAutoGUI / pywinauto / Playwright 연동
   - Kill Switch(ESC) 확인 후 실행
   - Undo Manager 에 액션 기록

단독 실행:
    python -m app.mcp_servers.automation_server
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from app.mcp_servers.base_server import (
    BaseMCPServer,
    MCPToolError,
    ToolNotImplementedError,
)

#: 이 서버의 실제 구현 예정 단계
PLANNED_STEP = "STEP 6 (Perception & Executor)"


class AutomationMCPServer(BaseMCPServer):
    """마우스/키보드/브라우저 조작 도구를 제공하는 MCP 서버. (위험 — 승인 필요)"""

    def __init__(self) -> None:
        super().__init__("automation")

    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="click",
                description=(
                    "지정한 화면 좌표를 마우스로 클릭합니다. "
                    "좌표는 screen.find_ui_element 로 먼저 확인하세요. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "클릭할 X 좌표"},
                        "y": {"type": "integer", "description": "클릭할 Y 좌표"},
                        "button": {
                            "type": "string",
                            "description": "마우스 버튼",
                            "enum": ["left", "right", "middle"],
                            "default": "left",
                        },
                    },
                    "required": ["x", "y"],
                },
            ),
            Tool(
                name="type_text",
                description=(
                    "현재 포커스된 입력창에 텍스트를 입력합니다. "
                    "먼저 입력창을 클릭해 포커스를 준 뒤 사용하세요. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "입력할 텍스트"}
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="key_press",
                description=(
                    "키보드 키를 누릅니다. 예: 'enter', 'tab', 'ctrl+c'. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "누를 키 이름 또는 조합 (예: enter, ctrl+c)",
                        }
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="open_browser",
                description=(
                    "브라우저로 지정한 주소를 엽니다. "
                    "허용된 도메인(화이트리스트)만 열 수 있습니다. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "열려는 웹 주소"}
                    },
                    "required": ["url"],
                },
            ),
        ]

    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다. (STEP 6 에서 실제 로직으로 교체)"""
        if name in {"click", "type_text", "key_press", "open_browser"}:
            raise ToolNotImplementedError(name, PLANNED_STEP)
        raise MCPToolError(f"automation 서버에 '{name}' 도구가 없습니다.")


def main() -> None:
    """단독 실행 진입점."""
    AutomationMCPServer.main()


if __name__ == "__main__":
    main()
