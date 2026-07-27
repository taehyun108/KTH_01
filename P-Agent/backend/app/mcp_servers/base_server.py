"""
P-Agent 내부 MCP 서버 베이스 클래스.

모든 도구 서버(filesystem / screen / automation / rag / report)는
이 클래스를 상속받아 구현한다.

설계 원칙
---------
1. **stdout 은 JSON-RPC 전용**
   MCP 는 stdin/stdout 으로 통신하므로 서버 코드에서 절대 `print()` 를 쓰면 안 된다.
   로그는 반드시 stderr 로 보낸다. (setup_server_logging 이 처리)

2. **경로 보안**
   파일을 다루는 도구는 반드시 `safe_project_path()` 로 경로를 검증해
   프로젝트 루트 밖으로 나가지 못하게 한다. (경로 탈출 공격 방지)

3. **에러는 한글로**
   `handle_call` 에서 발생한 예외는 MCP SDK 가 자동으로 잡아
   `isError=True` 결과로 변환한다. 따라서 예외 메시지를 한글로 작성하면
   그대로 사용자에게 전달된다.

4. **미구현 도구**
   아직 구현되지 않은 도구는 `ToolNotImplementedError` 를 던진다.
   서버는 정상 동작하고 해당 도구만 명확한 안내와 함께 실패한다.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ------------------------------------------------------------
# 프로젝트 루트 (절대경로 하드코딩 금지)
#   이 파일: <루트>/backend/app/mcp_servers/base_server.py
#   parents[0]=mcp_servers, [1]=app, [2]=backend, [3]=<루트>
# ------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


class MCPToolError(RuntimeError):
    """도구 실행 실패. 메시지는 사용자에게 그대로 노출되므로 한글로 작성한다."""


class ToolNotImplementedError(MCPToolError):
    """아직 구현되지 않은 도구를 호출한 경우."""

    def __init__(self, tool_name: str, planned_step: str) -> None:
        super().__init__(
            f"'{tool_name}' 도구는 아직 구현되지 않았습니다. ({planned_step} 에서 구현 예정)"
        )
        self.tool_name = tool_name
        self.planned_step = planned_step


def setup_server_logging(name: str) -> logging.Logger:
    """
    MCP 서버용 로거를 만든다.

    ⚠️ 반드시 stderr 로 출력해야 한다. stdout 은 JSON-RPC 통신 전용이라
       로그가 섞이면 통신이 깨진다.
    """
    logger = logging.getLogger(f"p-agent.mcp.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def safe_project_path(raw_path: str, *, must_exist: bool = False) -> Path:
    """
    사용자/LLM 이 준 경로를 **프로젝트 루트 하위로 제한**해 안전한 Path 로 변환한다.

    다음을 모두 차단한다:
      - 상위 디렉터리 탈출 (`../../etc/passwd`)
      - 프로젝트 밖 절대경로 (`/etc/passwd`, `C:\\Windows\\...`)
      - 심볼릭 링크를 통한 우회 (resolve() 로 실제 경로 확인)

    Args:
        raw_path: 검사할 경로 문자열 (프로젝트 루트 기준 상대경로 권장)
        must_exist: True 면 존재하지 않는 경로를 오류로 처리

    Returns:
        검증된 절대 Path

    Raises:
        MCPToolError: 프로젝트 폴더를 벗어나거나 존재하지 않는 경우
    """
    if not raw_path or not str(raw_path).strip():
        raise MCPToolError("경로가 비어 있습니다. 파일 경로를 입력하세요.")

    candidate = Path(str(raw_path).strip())
    # 상대경로는 프로젝트 루트 기준으로 해석한다.
    combined = candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)

    # strict=False: 아직 없는 파일(쓰기 대상)도 정규화할 수 있어야 한다.
    resolved = combined.resolve(strict=False)
    root = PROJECT_ROOT.resolve(strict=False)

    if not resolved.is_relative_to(root):
        raise MCPToolError(
            f"보안 정책상 프로젝트 폴더 밖의 경로는 사용할 수 없습니다: {raw_path}\n"
            f"(허용 범위: {root})"
        )

    if must_exist and not resolved.exists():
        raise MCPToolError(f"파일 또는 폴더를 찾을 수 없습니다: {raw_path}")

    return resolved


def to_relative(path: Path) -> str:
    """프로젝트 루트 기준 상대경로 문자열로 변환한다. (로그/응답 표시용)"""
    try:
        return path.resolve(strict=False).relative_to(PROJECT_ROOT.resolve(strict=False)).as_posix()
    except ValueError:  # pragma: no cover - safe_project_path 통과 시 발생하지 않음
        return path.as_posix()


class BaseMCPServer(ABC):
    """
    MCP 서버 베이스 클래스.

    하위 클래스는 `get_tools()` 와 `handle_call()` 두 개만 구현하면 된다.

    Example:
        class EmailMCPServer(BaseMCPServer):
            def __init__(self) -> None:
                super().__init__("email")

            def get_tools(self) -> list[Tool]:
                return [Tool(name="send_mail", description="...", inputSchema={...})]

            async def handle_call(self, name: str, arguments: dict) -> Any:
                if name == "send_mail":
                    return "발송 완료"
                raise MCPToolError(f"알 수 없는 도구입니다: {name}")

        if __name__ == "__main__":
            EmailMCPServer.main()
    """

    def __init__(self, name: str) -> None:
        """
        Args:
            name: 서버 이름 (mcp_config.json 의 키와 일치해야 한다)
        """
        self.name = name
        self.logger = setup_server_logging(name)
        self.server: Server = Server(name)
        self._register_handlers()

    # ------------------------------------------------------------
    # 하위 클래스 구현 대상
    # ------------------------------------------------------------
    @abstractmethod
    def get_tools(self) -> list[Tool]:
        """
        이 서버가 제공하는 도구 목록.

        `description` 은 LLM 이 "언제 이 도구를 쓸지" 판단하는 근거이므로
        구체적으로 작성한다.
        """

    @abstractmethod
    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """
        도구 호출을 처리한다.

        Args:
            name: 도구 이름
            arguments: 입력 인자 (MCP SDK 가 inputSchema 로 이미 검증함)

        Returns:
            str  → 텍스트 결과로 반환
            dict → 구조화된 결과(structuredContent)로 반환

        Raises:
            MCPToolError: 실행 실패 (한글 메시지가 사용자에게 전달됨)
        """

    # ------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------
    def _register_handlers(self) -> None:
        """MCP 프로토콜 핸들러를 등록한다."""

        @self.server.list_tools()
        async def _list_tools() -> list[Tool]:
            return self.get_tools()

        @self.server.call_tool()
        async def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
            self.logger.info("도구 호출: %s(%s)", name, arguments)
            result = await self.handle_call(name, arguments)
            return self._normalize_result(result)

    @staticmethod
    def _normalize_result(result: Any) -> Any:
        """
        도구 반환값을 MCP 응답 형태로 정규화한다.

        - dict  → 그대로 반환 (SDK 가 structuredContent + JSON 텍스트로 처리)
        - str   → TextContent 한 건
        - 그 외 → 문자열로 변환해 TextContent 한 건
        """
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return result
        if isinstance(result, str):
            return [TextContent(type="text", text=result)]
        return [TextContent(type="text", text=str(result))]

    def tool_names(self) -> list[str]:
        """제공 도구 이름 목록. (테스트/헬스체크용)"""
        return [tool.name for tool in self.get_tools()]

    # ------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------
    async def run(self) -> None:
        """MCP 서버를 stdio 모드로 실행한다. (프로세스가 종료될 때까지 대기)"""
        self.logger.info("MCP 서버 시작: %s (도구 %d개)", self.name, len(self.tool_names()))
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )

    @classmethod
    def main(cls) -> None:
        """`python -m app.mcp_servers.xxx_server` 로 실행하기 위한 진입점."""
        try:
            asyncio.run(cls().run())  # type: ignore[call-arg]
        except KeyboardInterrupt:  # pragma: no cover - 사용자 종료
            pass
