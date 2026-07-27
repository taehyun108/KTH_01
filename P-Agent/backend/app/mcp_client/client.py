"""
P-Agent MCP 클라이언트.

내부 MCP 서버들을 **별도 프로세스로 기동**하고 JSON-RPC(stdio)로 통신한다.

포터블 설계
-----------
1. `mcp_config.json` 의 `"command": "python"` 은 **현재 가상환경의 파이썬**
   (`sys.executable`)으로 자동 치환한다.
   → 시스템 PATH 에 어떤 python 이 있든 상관없이 동작한다.

2. 서버 프로세스의 작업 디렉터리를 `backend/` 로 고정하고 `PYTHONPATH` 를 주입한다.
   → `-m app.mcp_servers.xxx` 가 항상 해석된다.

3. `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` 을 강제한다.
   → 한글 Windows(cp949) 환경에서 한글이 깨져 JSON-RPC 가 실패하는 문제를 방지한다.

단독 실행 (헬스체크):
    python -m app.mcp_client --healthcheck
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.types import Tool

# ------------------------------------------------------------
# 경로 (절대경로 하드코딩 금지)
#   이 파일: <루트>/backend/app/mcp_client/client.py
# ------------------------------------------------------------
BACKEND_DIR: Path = Path(__file__).resolve().parents[2]
PROJECT_ROOT: Path = BACKEND_DIR.parent
DEFAULT_CONFIG_PATH: Path = BACKEND_DIR / "app" / "mcp_servers" / "mcp_config.json"

#: 서버 기동/도구 호출 기본 타임아웃(초)
DEFAULT_TIMEOUT: float = 60.0

#: 클라이언트 내부 로거 (stdout 은 JSON-RPC 전용이므로 사용하지 않는다)
_logger = logging.getLogger("p-agent.mcp.client")


class MCPClientError(RuntimeError):
    """MCP 클라이언트 오류. 메시지는 사용자에게 노출되므로 한글로 작성한다."""


@dataclass(frozen=True)
class MCPServerConfig:
    """mcp_config.json 의 서버 한 건."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    enabled: bool = True
    require_approval: bool = False
    description: str = ""

    def resolved_command(self) -> str:
        """
        실행할 명령을 결정한다.

        "python" / "python3" 은 현재 가상환경의 인터프리터로 치환해
        시스템 PATH 의존성을 제거한다. (포터블 원칙)
        """
        if self.command.strip().lower() in {"python", "python3", "py"}:
            return sys.executable
        return self.command


@dataclass(frozen=True)
class MCPToolResult:
    """도구 실행 결과."""

    server: str
    tool: str
    text: str
    """텍스트로 합쳐진 결과."""

    structured: dict[str, Any] | None = None
    """구조화된 결과(있는 경우)."""

    is_error: bool = False

    def raise_for_error(self) -> MCPToolResult:
        """실패한 결과면 예외를 던진다."""
        if self.is_error:
            raise MCPClientError(f"[{self.server}.{self.tool}] {self.text}")
        return self


def load_mcp_config(config_path: Path | None = None) -> dict[str, MCPServerConfig]:
    """
    `mcp_config.json` 을 읽어 서버 설정을 반환한다.

    Args:
        config_path: 설정 파일 경로. 생략 시 기본 위치를 사용한다.

    Returns:
        {서버이름: MCPServerConfig}

    Raises:
        MCPClientError: 파일이 없거나 형식이 잘못된 경우
    """
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise MCPClientError(
            f"MCP 설정 파일을 찾을 수 없습니다: {path}\n"
            f"파일이 삭제되었는지 확인하세요."
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPClientError(
            f"MCP 설정 파일 형식이 잘못되었습니다: {path}\n({exc})"
        ) from exc

    servers = raw.get("servers")
    if not isinstance(servers, dict):
        raise MCPClientError(
            f"MCP 설정 파일에 'servers' 항목이 없습니다: {path}"
        )

    configs: dict[str, MCPServerConfig] = {}
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        configs[name] = MCPServerConfig(
            name=name,
            command=entry.get("command", "python"),
            args=list(entry.get("args", [])),
            enabled=bool(entry.get("enabled", True)),
            require_approval=bool(entry.get("require_approval", False)),
            description=entry.get("description", ""),
        )
    return configs


def build_server_env() -> dict[str, str]:
    """
    MCP 서버 프로세스에 전달할 환경변수를 만든다.

    - PYTHONPATH: `-m app.mcp_servers.xxx` 해석용
    - PYTHONUTF8 / PYTHONIOENCODING: 한글 Windows 에서 인코딩 깨짐 방지
    - PYTHONDONTWRITEBYTECODE: USB 에 __pycache__ 를 남기지 않음
    """
    env = dict(get_default_environment())
    env.update(
        {
            "PYTHONPATH": str(BACKEND_DIR),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return env


class _ServerConnection:
    """
    MCP 서버 한 개의 연결 생명주기를 **전용 task 안에서** 관리한다.

    ⚠️ 왜 전용 task 가 필요한가
    ---------------------------
    `stdio_client()` 는 내부적으로 anyio cancel scope 를 연다.
    anyio 규칙상 **cancel scope 는 진입한 것과 동일한 task 에서 종료**해야 한다.
    따라서 연결을 A task 에서 열고 B task 에서 닫으면
    `RuntimeError: Attempted to exit cancel scope in a different task` 가 발생한다.

    (FastAPI lifespan, pytest 픽스처, 백그라운드 워커 등은 setup/teardown 이
     서로 다른 task 에서 실행될 수 있으므로 실제로 자주 터지는 문제다)

    해결: 연결을 여는 것도 닫는 것도 이 클래스가 만든 **하나의 task** 가 담당한다.
    외부 task 는 준비 완료 신호를 기다렸다가 `session` 을 빌려 쓰기만 한다.
    (메모리 스트림 기반 세션 객체는 task 간 공유해도 안전하다)
    """

    def __init__(self, config: MCPServerConfig, timeout: float) -> None:
        self.config = config
        self.timeout = timeout
        self.session: ClientSession | None = None
        self.tools: list[Tool] = []
        self.error: str | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """서버 프로세스를 기동하고 초기화가 끝날 때까지 기다린다."""
        self._task = asyncio.create_task(self._run(), name=f"mcp-{self.config.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self.timeout)
        except TimeoutError as exc:
            await self.stop()
            raise MCPClientError(
                f"'{self.config.name}' 서버가 {self.timeout:.0f}초 안에 시작되지 않았습니다."
            ) from exc

        if self.error is not None:
            await self.stop()
            raise MCPClientError(f"'{self.config.name}' 서버 시작 실패: {self.error}")

    async def _run(self) -> None:
        """연결을 열고 종료 신호가 올 때까지 유지한다. (이 task 안에서 열고 닫는다)"""
        params = StdioServerParameters(
            command=self.config.resolved_command(),
            args=self.config.args,
            cwd=str(BACKEND_DIR),
            env=build_server_env(),
        )
        try:
            async with (
                stdio_client(params) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await asyncio.wait_for(session.initialize(), timeout=self.timeout)
                response = await asyncio.wait_for(
                    session.list_tools(), timeout=self.timeout
                )
                self.session = session
                self.tools = list(response.tools)
                self._ready.set()
                # 종료 신호가 올 때까지 연결을 유지한다.
                await self._shutdown.wait()
        except asyncio.CancelledError:  # pragma: no cover - 강제 종료 경로
            raise
        except Exception as exc:  # noqa: BLE001 - 개별 서버 실패를 격리
            self.error = str(exc)
        finally:
            self.session = None
            self._ready.set()  # 실패해도 start() 가 무한 대기하지 않도록 한다.

    async def stop(self) -> None:
        """서버 프로세스를 종료한다."""
        self._shutdown.set()
        task = self._task
        if task is None:
            return
        if not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout)
            except (TimeoutError, asyncio.CancelledError):  # pragma: no cover
                task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # 강제 종료는 정상 경로
        except Exception as exc:  # noqa: BLE001 - 종료 중 오류는 치명적이지 않다
            _logger.debug("'%s' 서버 종료 중 오류: %s", self.config.name, exc)
        self._task = None


class MCPClient:
    """
    여러 MCP 서버를 동시에 관리하는 클라이언트.

    ⚠️ 반드시 `async with` 로 사용한다. (서브프로세스 생명주기를 안전하게 정리하기 위함)

    Example:
        async with MCPClient.from_config() as client:
            tools = client.list_tools()
            result = await client.call_tool("filesystem", "list_dir", {"path": "."})
    """

    def __init__(
        self,
        configs: dict[str, MCPServerConfig],
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.configs = configs
        self.timeout = timeout
        self._connections: dict[str, _ServerConnection] = {}
        self._failed: dict[str, str] = {}
        self._connected = False

    # ------------------------------------------------------------
    # 생성
    # ------------------------------------------------------------
    @classmethod
    def from_config(
        cls, config_path: Path | None = None, *, timeout: float = DEFAULT_TIMEOUT
    ) -> MCPClient:
        """`mcp_config.json` 을 읽어 클라이언트를 만든다."""
        return cls(load_mcp_config(config_path), timeout=timeout)

    # ------------------------------------------------------------
    # 연결 관리
    # ------------------------------------------------------------
    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def connect(self) -> None:
        """
        활성화된 모든 MCP 서버를 기동하고 도구 목록을 수집한다.

        일부 서버가 실패해도 나머지는 정상 동작하도록 한다.
        (실패 내역은 `failed_servers` 로 확인)
        """
        if self._connected:
            return  # 이미 연결됨
        self._connected = True

        for name, config in self.configs.items():
            if not config.enabled:
                continue
            connection = _ServerConnection(config, self.timeout)
            try:
                await connection.start()
            except Exception as exc:  # noqa: BLE001 - 개별 서버 실패를 격리
                self._failed[name] = str(exc)
                continue
            self._connections[name] = connection

    async def aclose(self) -> None:
        """모든 서버 프로세스를 종료한다."""
        for connection in list(self._connections.values()):
            await connection.stop()
        self._connections.clear()
        self._connected = False

    # ------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------
    @property
    def connected_servers(self) -> list[str]:
        """정상 연결된 서버 이름 목록."""
        return sorted(self._connections.keys())

    @property
    def failed_servers(self) -> dict[str, str]:
        """연결 실패한 서버와 사유."""
        return dict(self._failed)

    def list_tools(self) -> dict[str, list[Tool]]:
        """서버별 도구 목록을 반환한다."""
        return {
            name: list(connection.tools)
            for name, connection in self._connections.items()
        }

    def total_tool_count(self) -> int:
        """수집된 전체 도구 개수."""
        return sum(len(connection.tools) for connection in self._connections.values())

    # ------------------------------------------------------------
    # 도구 실행
    # ------------------------------------------------------------
    async def call_tool(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPToolResult:
        """
        지정한 서버의 도구를 실행한다.

        Args:
            server: 서버 이름 (예: "filesystem")
            tool: 도구 이름 (예: "read_file")
            arguments: 입력 인자

        Returns:
            MCPToolResult (실패해도 예외를 던지지 않고 is_error=True 로 반환)

        Raises:
            MCPClientError: 서버가 연결되어 있지 않은 경우
        """
        connection = self._connections.get(server)
        session = connection.session if connection else None
        if session is None:
            available = ", ".join(self.connected_servers) or "(없음)"
            raise MCPClientError(
                f"'{server}' MCP 서버가 연결되어 있지 않습니다. "
                f"사용 가능한 서버: {available}"
            )

        try:
            result = await asyncio.wait_for(
                session.call_tool(tool, arguments or {}), timeout=self.timeout
            )
        except TimeoutError as exc:
            raise MCPClientError(
                f"'{server}.{tool}' 도구 실행이 {self.timeout:.0f}초 안에 끝나지 않았습니다."
            ) from exc

        texts: list[str] = []
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                texts.append(text)

        return MCPToolResult(
            server=server,
            tool=tool,
            text="\n".join(texts),
            structured=result.structuredContent,
            is_error=bool(result.isError),
        )


# ============================================================
# 헬스체크 CLI (run_all.bat 에서 호출)
# ============================================================


async def _run_healthcheck(config_path: Path | None = None) -> int:
    """모든 MCP 서버를 기동해 정상 동작하는지 확인하고 결과를 출력한다."""
    print("=" * 56)
    print("  P-Agent 내부 도구 서버(MCP) 헬스체크")
    print("=" * 56)

    try:
        client = MCPClient.from_config(config_path)
    except MCPClientError as exc:
        print(f"  [!] {exc}")
        return 1

    disabled = [name for name, cfg in client.configs.items() if not cfg.enabled]

    # ⚠️ 집계는 반드시 `async with` 블록 **안에서** 해야 한다.
    #    블록을 벗어나면 aclose() 가 세션 정보를 비우므로 0 으로 집계된다.
    async with client:
        for name in client.connected_servers:
            tools = client.list_tools()[name]
            approval = " (승인 필요)" if client.configs[name].require_approval else ""
            print(f"  [OK] {name:<12} 도구 {len(tools)}개{approval}")
            for tool in tools:
                print(f"         - {name}.{tool.name}")

        for name, reason in client.failed_servers.items():
            print(f"  [실패] {name:<12} {reason}")

        for name in disabled:
            print(f"  [건너뜀] {name:<12} (mcp_config.json 에서 비활성화됨)")

        connected_count = len(client.connected_servers)
        total = client.total_tool_count()
        failed_count = len(client.failed_servers)

    print("-" * 56)
    if failed_count:
        print(f"  ⚠️  서버 {failed_count}개가 시작되지 않았습니다. 일부 기능이 제한됩니다.")
        print("=" * 56)
        return 1

    print(f"  ✅ 정상: 서버 {connected_count}개 / 도구 {total}개")
    print("=" * 56)
    return 0


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(description="P-Agent MCP 클라이언트")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="모든 MCP 서버를 기동해 정상 동작하는지 확인합니다.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="mcp_config.json 경로 (생략 시 기본 위치)",
    )
    args = parser.parse_args()

    if args.healthcheck:
        raise SystemExit(asyncio.run(_run_healthcheck(args.config)))

    parser.print_help()


if __name__ == "__main__":
    main()
