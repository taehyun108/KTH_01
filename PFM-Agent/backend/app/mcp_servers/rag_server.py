"""
rag MCP 서버 — 사내 문서 검색 도구. (STEP 7 구현)

제공 도구:
  - search_internal_docs(query, top_k) : 사내 문서 검색
  - add_document(path)                 : 문서를 색인에 추가

폐쇄망 대응
-----------
이 서버는 **인터넷 없이 동작**해야 한다.
  - 의미 검색: 로컬 BGE-M3 (`./models/bge-m3`) + ChromaDB 임베디드
  - 모델이 없으면 **키워드 검색으로 자동 대체** → 기능이 완전히 죽지 않는다

검색 결과에는 어떤 방식(vector/keyword)으로 찾았는지 표시해
사용자가 결과의 정확도를 판단할 수 있게 한다.

개인정보 보호
-------------
검색 결과는 **마스킹을 거쳐** 반환한다.
사내 문서에 포함된 주민번호·연락처가 LLM 이나 보고서로 흘러가는 것을 막는다.

단독 실행:
    python -m app.mcp_servers.rag_server
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from app.mcp_servers.base_server import (
    PROJECT_ROOT,
    BaseMCPServer,
    MCPToolError,
    safe_project_path,
)
from app.rag.vector_store import VectorStore
from app.security.masking import mask_text

#: 검색 결과 본문 최대 길이 (LLM 컨텍스트 보호)
MAX_CONTENT_CHARS: int = 2000


class RagMCPServer(BaseMCPServer):
    """사내 문서 검색(RAG) 도구를 제공하는 MCP 서버."""

    def __init__(self) -> None:
        super().__init__("rag")
        self._store: VectorStore | None = None

    @property
    def store(self) -> VectorStore:
        """검색 저장소를 지연 생성한다. (서버 기동을 빠르게 하기 위함)"""
        if self._store is None:
            self._store = VectorStore(
                data_dir=PROJECT_ROOT / "data",
                model_path=PROJECT_ROOT / "models" / "bge-m3",
                chroma_dir=PROJECT_ROOT / "data" / "chroma",
            )
            self.logger.info("검색 저장소 준비: %s", self._store.status())
        return self._store

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
        """도구 호출을 처리한다."""
        if name == "search_internal_docs":
            return self._search(arguments["query"], int(arguments.get("top_k", 5)))
        if name == "add_document":
            return self._add_document(arguments["path"])
        raise MCPToolError(f"rag 서버에 '{name}' 도구가 없습니다.")

    # ------------------------------------------------------------
    # 개별 도구 구현
    # ------------------------------------------------------------
    def _search(self, query: str, top_k: int) -> dict[str, Any]:
        """사내 문서를 검색한다. (결과는 마스킹 후 반환)"""
        if not query.strip():
            raise MCPToolError("검색할 내용을 입력하세요.")

        store = self.store
        if store.document_count == 0:
            return {
                "query": query,
                "count": 0,
                "results": [],
                "method": store.method,
                "message": (
                    "색인된 사내 문서가 없습니다.\n"
                    "  rag.add_document 도구로 문서를 추가하거나, "
                    "./data 폴더에 자료를 넣은 뒤 다시 시도하세요."
                ),
            }

        found = store.search(query, top_k=max(1, min(top_k, 20)))

        results: list[dict[str, Any]] = []
        masked_total = 0
        for item in found:
            masked = mask_text(item.content[:MAX_CONTENT_CHARS])
            masked_total += masked.total
            entry = item.to_dict()
            entry["content"] = masked.text
            results.append(entry)

        message = f"사내 문서에서 {len(results)}건을 찾았습니다."
        if store.method == "keyword":
            message += " (키워드 검색 — 의미 검색 모델이 준비되면 정확도가 올라갑니다)"
        if masked_total:
            message += f" 개인정보 {masked_total}건은 가려서 표시했습니다."

        return {
            "query": query,
            "count": len(results),
            "results": results,
            "method": store.method,
            "message": message,
        }

    def _add_document(self, raw_path: str) -> dict[str, Any]:
        """문서를 색인에 추가한다."""
        target = safe_project_path(raw_path, must_exist=True)

        try:
            added = self.store.add_document(target, relative_to=PROJECT_ROOT)
        except ValueError as exc:
            raise MCPToolError(str(exc)) from exc

        return {
            "path": target.relative_to(PROJECT_ROOT).as_posix(),
            "chunks_added": added,
            "total_chunks": self.store.document_count,
            "method": self.store.method,
            "message": f"'{target.name}' 을(를) 색인에 추가했습니다. ({added}개 조각)",
        }


def main() -> None:
    """단독 실행 진입점."""
    RagMCPServer.main()


if __name__ == "__main__":
    main()
