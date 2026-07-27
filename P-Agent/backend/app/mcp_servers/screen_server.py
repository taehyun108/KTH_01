"""
screen MCP 서버 — 화면 인식 도구.

제공 도구:
  - capture_screen()            : 전체 화면 캡처
  - find_ui_element(description): 자연어로 UI 요소 위치 탐지 (OmniParser)
  - ocr_region(bbox)            : 지정 영역 텍스트 인식 (PaddleOCR)

⚠️ 현재 상태: **도구 스키마만 정의된 스텁(stub)**
   실제 구현은 STEP 6 (Perception & Executor) 에서 채운다.
   스키마가 이미 확정되어 있으므로 STEP 6 에서는 `handle_call` 본문만 작성하면 되고,
   MCP 클라이언트/레지스트리/Agent 코드는 수정할 필요가 없다.

단독 실행:
    python -m app.mcp_servers.screen_server
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


class ScreenMCPServer(BaseMCPServer):
    """화면 캡처 / UI 요소 탐지 / OCR 도구를 제공하는 MCP 서버."""

    def __init__(self) -> None:
        super().__init__("screen")

    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="capture_screen",
                description=(
                    "현재 화면 전체를 캡처해 이미지 파일로 저장하고 경로를 반환합니다. "
                    "PC 화면 상태를 확인해야 조작을 결정할 수 있을 때 가장 먼저 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "region": {
                            "type": "array",
                            "description": (
                                "캡처할 영역 [x, y, width, height]. "
                                "생략하면 전체 화면을 캡처합니다."
                            ),
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        }
                    },
                    "required": [],
                },
            ),
            Tool(
                name="find_ui_element",
                description=(
                    "화면에서 자연어 설명과 일치하는 UI 요소(버튼/입력창/링크 등)의 "
                    "위치와 좌표를 찾습니다. 예: '검색 버튼', '주소 입력창'. "
                    "클릭할 좌표를 알아내야 할 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "찾을 UI 요소에 대한 자연어 설명",
                        }
                    },
                    "required": ["description"],
                },
            ),
            Tool(
                name="ocr_region",
                description=(
                    "화면의 지정한 영역에서 텍스트를 인식해 반환합니다. "
                    "화면에 표시된 문자를 읽어야 할 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bbox": {
                            "type": "array",
                            "description": "인식할 영역 [x1, y1, x2, y2]",
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        }
                    },
                    "required": ["bbox"],
                },
            ),
        ]

    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다. (STEP 6 에서 실제 로직으로 교체)"""
        if name in {"capture_screen", "find_ui_element", "ocr_region"}:
            raise ToolNotImplementedError(name, PLANNED_STEP)
        raise MCPToolError(f"screen 서버에 '{name}' 도구가 없습니다.")


def main() -> None:
    """단독 실행 진입점."""
    ScreenMCPServer.main()


if __name__ == "__main__":
    main()
