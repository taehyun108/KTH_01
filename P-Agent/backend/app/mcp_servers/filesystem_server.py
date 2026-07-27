"""
filesystem MCP 서버 — 파일 조작 도구.

제공 도구:
  - read_file(path)            : 파일 읽기
  - write_file(path, content)  : 파일 쓰기
  - list_dir(path)             : 디렉터리 목록

보안:
  모든 경로는 `safe_project_path()` 를 통과해야 하며,
  **프로젝트 루트 하위로만** 접근할 수 있다.
  (`../../etc/passwd`, `C:\\Windows\\...` 등은 모두 차단)

단독 실행:
    python -m app.mcp_servers.filesystem_server
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from app.mcp_servers.base_server import (
    BaseMCPServer,
    MCPToolError,
    safe_project_path,
    to_relative,
)

#: 한 번에 읽을 수 있는 최대 파일 크기 (LLM 컨텍스트 보호)
MAX_READ_BYTES: int = 1_000_000  # 약 1MB

#: 디렉터리 목록에 표시할 최대 항목 수
MAX_LIST_ENTRIES: int = 500


class FilesystemMCPServer(BaseMCPServer):
    """파일 읽기/쓰기/목록 도구를 제공하는 MCP 서버."""

    def __init__(self) -> None:
        super().__init__("filesystem")

    # ------------------------------------------------------------
    # 도구 정의
    # ------------------------------------------------------------
    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="read_file",
                description=(
                    "지정한 파일의 내용을 읽어 문자열로 반환합니다. "
                    "보고서 작성에 필요한 자료나 이전에 저장한 결과를 확인할 때 사용하세요. "
                    "경로는 프로젝트 폴더 기준 상대경로여야 합니다 (예: ./data/policy.md)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "읽을 파일 경로 (프로젝트 폴더 기준 상대경로)",
                        }
                    },
                    "required": ["path"],
                },
            ),
            Tool(
                name="write_file",
                description=(
                    "지정한 경로에 텍스트 파일을 저장합니다. 기존 파일이 있으면 덮어씁니다. "
                    "중간 결과나 정리한 내용을 보관할 때 사용하세요. "
                    "저장 위치는 ./output 또는 ./data 를 권장합니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "저장할 파일 경로 (프로젝트 폴더 기준 상대경로)",
                        },
                        "content": {
                            "type": "string",
                            "description": "파일에 쓸 텍스트 내용",
                        },
                    },
                    "required": ["path", "content"],
                },
            ),
            Tool(
                name="list_dir",
                description=(
                    "지정한 폴더 안의 파일과 하위 폴더 목록을 반환합니다. "
                    "어떤 자료가 있는지 먼저 확인할 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "조회할 폴더 경로 (기본값: 프로젝트 루트 '.')",
                            "default": ".",
                        }
                    },
                    "required": [],
                },
            ),
        ]

    # ------------------------------------------------------------
    # 도구 실행
    # ------------------------------------------------------------
    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다."""
        if name == "read_file":
            return self._read_file(arguments["path"])
        if name == "write_file":
            return self._write_file(arguments["path"], arguments["content"])
        if name == "list_dir":
            return self._list_dir(arguments.get("path", "."))
        raise MCPToolError(f"filesystem 서버에 '{name}' 도구가 없습니다.")

    # ------------------------------------------------------------
    # 개별 도구 구현
    # ------------------------------------------------------------
    @staticmethod
    def _read_file(raw_path: str) -> dict[str, Any]:
        """파일을 읽어 내용을 반환한다."""
        target = safe_project_path(raw_path, must_exist=True)

        if target.is_dir():
            raise MCPToolError(
                f"'{raw_path}' 은(는) 폴더입니다. 파일 경로를 입력하거나 list_dir 도구를 사용하세요."
            )

        size = target.stat().st_size
        if size > MAX_READ_BYTES:
            raise MCPToolError(
                f"파일이 너무 큽니다 ({size:,} 바이트). "
                f"{MAX_READ_BYTES:,} 바이트 이하의 파일만 읽을 수 있습니다."
            )

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise MCPToolError(
                f"'{raw_path}' 은(는) 텍스트 파일이 아니거나 UTF-8 인코딩이 아닙니다. "
                f"(이미지/PDF 등 이진 파일은 이 도구로 읽을 수 없습니다)"
            ) from exc

        return {
            "path": to_relative(target),
            "size_bytes": size,
            "content": content,
        }

    @staticmethod
    def _write_file(raw_path: str, content: str) -> dict[str, Any]:
        """파일에 텍스트를 저장한다. 상위 폴더가 없으면 만든다."""
        target = safe_project_path(raw_path)

        if target.is_dir():
            raise MCPToolError(f"'{raw_path}' 은(는) 이미 폴더로 존재합니다. 다른 경로를 지정하세요.")

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise MCPToolError(f"파일을 저장하지 못했습니다: {raw_path} ({exc})") from exc

        return {
            "path": to_relative(target),
            "size_bytes": target.stat().st_size,
            "message": f"저장 완료: {to_relative(target)}",
        }

    @staticmethod
    def _list_dir(raw_path: str) -> dict[str, Any]:
        """폴더 내용을 나열한다."""
        target = safe_project_path(raw_path, must_exist=True)

        if not target.is_dir():
            raise MCPToolError(
                f"'{raw_path}' 은(는) 폴더가 아닙니다. 파일 내용을 보려면 read_file 을 사용하세요."
            )

        entries: list[dict[str, Any]] = []
        # 폴더 먼저, 그다음 파일 (각각 이름순)
        children = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        truncated = len(children) > MAX_LIST_ENTRIES

        for child in children[:MAX_LIST_ENTRIES]:
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size_bytes": child.stat().st_size if child.is_file() else None,
                    "path": to_relative(child),
                }
            )

        return {
            "path": to_relative(target),
            "count": len(entries),
            "truncated": truncated,
            "entries": entries,
        }


def main() -> None:
    """단독 실행 진입점."""
    FilesystemMCPServer.main()


if __name__ == "__main__":
    main()
