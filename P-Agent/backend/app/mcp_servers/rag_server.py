"""
rag MCP 서버 — 사내 문서 검색 도구.

제공 도구:
  - search_internal_docs(query, top_k) : 사내 문서 벡터 검색
  - add_document(path)                 : 문서를 색인에 추가

폐쇄망 대응:
  이 서버는 **인터넷 없이 동작**해야 한다.
  - 임베딩: 로컬 BGE-M3 (`./models/bge-m3`)
  - 벡터 DB: ChromaDB 임베디드 모드 (`./data/chroma`)
  웹 검색이 실패해도 이 서버만으로 Retriever Agent 가 동작할 수 있어야 한다.

⚠️ 현재 상태: **도구 스키마만 정의된 스텁(stub)**
   실제 구현은 STEP 7 (Retriever & Verifier) 에서 채운다.

단독 실행:
    python -m app.mcp_servers.rag_server
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
PLANNED_STEP = "STEP 7 (Retriever & Verifier)"


class RagMCPServer(BaseMCPServer):
    """사내 문서 검색(RAG) 도구를 제공하는 MCP 서버."""

    def __init__(self) -> None:
        super().__init__("rag")

    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="search_internal_docs",
                description=(
                    "사내 문서 저장소에서 질문과 관련된 내용을 검색해 "
                    "출처와 함께 반환합니다. 사내 자료·규정·과거 보고서 내용이 필요할 때 "
                    "가장 먼저 사용하세요. 인터넷 연결 없이도 동작합니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "검색할 질문이나 키워드",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "가져올 문서 조각 개수 (기본 5)",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="add_document",
                description=(
                    "지정한 문서 파일을 사내 검색 색인에 추가합니다. "
                    "새로운 참고 자료를 검색 대상에 포함시킬 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "색인에 추가할 문서 경로 (프로젝트 폴더 기준 상대경로)",
                        }
                    },
                    "required": ["path"],
                },
            ),
        ]

    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다. (STEP 7 에서 실제 로직으로 교체)"""
        if name in {"search_internal_docs", "add_document"}:
            raise ToolNotImplementedError(name, PLANNED_STEP)
        raise MCPToolError(f"rag 서버에 '{name}' 도구가 없습니다.")


def main() -> None:
    """단독 실행 진입점."""
    RagMCPServer.main()


if __name__ == "__main__":
    main()
