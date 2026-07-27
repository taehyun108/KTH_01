"""
report MCP 서버 — 보고서 생성 도구.

제공 도구:
  - create_word_report(title, sections, citations) : Word(.docx) 보고서 생성
  - create_ppt_report(title, slides, citations)    : PowerPoint(.pptx) 보고서 생성

산출물은 모두 프로젝트 폴더 내부(`./output`)에 저장한다. (포터블 원칙)

⚠️ 현재 상태: **도구 스키마만 정의된 스텁(stub)**
   실제 구현은 STEP 8 (Report Generator) 에서 python-docx / python-pptx 로 채운다.

단독 실행:
    python -m app.mcp_servers.report_server
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
PLANNED_STEP = "STEP 8 (Report Generator)"

#: 인용(각주) 항목 스키마 — Word/PPT 공통
_CITATION_SCHEMA: dict[str, Any] = {
    "type": "array",
    "description": "각주로 넣을 출처 목록. 근거가 있는 내용에는 반드시 출처를 붙이세요.",
    "items": {
        "type": "object",
        "properties": {
            "label": {"type": "string", "description": "출처 표시 이름"},
            "source": {"type": "string", "description": "출처 경로 또는 URL"},
            "quote": {"type": "string", "description": "인용한 원문 (선택)"},
        },
        "required": ["label", "source"],
    },
}


class ReportMCPServer(BaseMCPServer):
    """Word / PowerPoint 보고서 생성 도구를 제공하는 MCP 서버."""

    def __init__(self) -> None:
        super().__init__("report")

    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="create_word_report",
                description=(
                    "제목과 본문 섹션으로 Word(.docx) 보고서를 만들어 "
                    "./output 폴더에 저장하고 파일 경로를 반환합니다. "
                    "정부 부처 대응 보고서 등 문서 형태의 최종 산출물을 만들 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "보고서 제목"},
                        "sections": {
                            "type": "array",
                            "description": "본문 섹션 목록 (순서대로 문서에 작성됨)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "heading": {"type": "string", "description": "섹션 제목"},
                                    "body": {"type": "string", "description": "섹션 본문"},
                                },
                                "required": ["heading", "body"],
                            },
                        },
                        "citations": _CITATION_SCHEMA,
                        "filename": {
                            "type": "string",
                            "description": "저장할 파일 이름 (생략 시 제목과 날짜로 자동 생성)",
                        },
                    },
                    "required": ["title", "sections"],
                },
            ),
            Tool(
                name="create_ppt_report",
                description=(
                    "제목과 슬라이드 목록으로 PowerPoint(.pptx) 보고서를 만들어 "
                    "./output 폴더에 저장하고 파일 경로를 반환합니다. "
                    "발표용 요약 자료가 필요할 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "발표 자료 제목"},
                        "slides": {
                            "type": "array",
                            "description": "슬라이드 목록 (순서대로 생성됨)",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "heading": {"type": "string", "description": "슬라이드 제목"},
                                    "bullets": {
                                        "type": "array",
                                        "description": "본문 글머리 기호 목록",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["heading", "bullets"],
                            },
                        },
                        "citations": _CITATION_SCHEMA,
                        "filename": {
                            "type": "string",
                            "description": "저장할 파일 이름 (생략 시 제목과 날짜로 자동 생성)",
                        },
                    },
                    "required": ["title", "slides"],
                },
            ),
        ]

    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다. (STEP 8 에서 실제 로직으로 교체)"""
        if name in {"create_word_report", "create_ppt_report"}:
            raise ToolNotImplementedError(name, PLANNED_STEP)
        raise MCPToolError(f"report 서버에 '{name}' 도구가 없습니다.")


def main() -> None:
    """단독 실행 진입점."""
    ReportMCPServer.main()


if __name__ == "__main__":
    main()
