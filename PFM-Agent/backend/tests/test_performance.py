"""
성능·자원 최적화 검증.

"빠르다"는 주장은 측정으로만 확인할 수 있으므로, 최적화가 **실제로 적용된
상태인지**를 코드 동작으로 검증한다. (절대 시간은 PC 성능에 따라 달라지므로
느슨한 상한만 두고, 구조적 성질을 주로 확인한다)

검증 항목
---------
1. MCP 서버가 **동시에** 기동되는가 (순차 기동 대비 빠른가)
2. 종료도 동시에 수행되는가
3. 컴파일된 그래프가 재사용되는가 (실행마다 재컴파일하지 않는가)
4. 이벤트 기록이 무한히 쌓이지 않는가 (메모리 상한)
5. 실행 기록이 무한히 쌓이지 않는가 (진행 중인 실행은 보존)
6. 도구 조회가 상수 시간인가
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agents.graph import build_graph, get_graph
from app.agents.run_manager import RunManager, RunRecord
from app.agents.runtime import (
    MAX_EVENTS_PER_RUN,
    MAX_TRACKED_RUNS,
    AgentEvent,
    AgentRuntime,
    EventBus,
)
from app.config.settings import load_settings
from app.mcp_client.client import MCPClient
from tests.test_feedback_loop import ScriptedLLM

CONNECT_TIMEOUT = 60.0

#: 서버 5개 동시 기동 상한(초). 순차 기동이면 이 값을 넘는다.
#: (컨테이너/저사양 PC 편차를 감안해 넉넉하게 잡는다)
PARALLEL_CONNECT_BUDGET = 6.0


@pytest.fixture
async def mcp_client() -> AsyncIterator[MCPClient]:
    """실제 MCP 서버를 기동한 클라이언트."""
    client = MCPClient.from_config(timeout=CONNECT_TIMEOUT)
    async with client:
        yield client


# ============================================================
# 1. MCP 서버 동시 기동 / 종료
# ============================================================


async def test_servers_start_concurrently() -> None:
    """
    서버 여러 개를 기동하는 시간이 **서버 1개 기동 시간에 가까워야** 한다.

    순차 기동이면 (1개 시간 × 서버 수) 만큼 걸리므로 이 검증에서 걸린다.
    """
    client = MCPClient.from_config(timeout=CONNECT_TIMEOUT)
    server_count = sum(1 for cfg in client.configs.values() if cfg.enabled)
    assert server_count >= 2, "동시 기동을 검증하려면 서버가 2개 이상이어야 한다"

    start = time.perf_counter()
    await client.connect()
    elapsed = time.perf_counter() - start
    try:
        assert len(client.connected_servers) == server_count
    finally:
        await client.aclose()

    assert elapsed < PARALLEL_CONNECT_BUDGET, (
        f"서버 {server_count}개 기동에 {elapsed:.2f}초가 걸렸습니다. "
        f"순차 기동으로 되돌아갔는지 확인하세요."
    )


async def test_close_is_concurrent(mcp_client: MCPClient) -> None:
    """종료도 서버 수에 비례하지 않아야 한다."""
    start = time.perf_counter()
    await mcp_client.aclose()
    elapsed = time.perf_counter() - start

    assert elapsed < PARALLEL_CONNECT_BUDGET
    # 종료 후에는 연결이 남아 있지 않아야 한다.
    assert mcp_client.connected_servers == []


async def test_connect_is_idempotent(mcp_client: MCPClient) -> None:
    """이미 연결된 상태에서 connect() 를 다시 불러도 서버를 또 띄우지 않아야 한다."""
    before = len(mcp_client.connected_servers)
    await mcp_client.connect()
    assert len(mcp_client.connected_servers) == before


async def test_one_bad_server_does_not_block_others() -> None:
    """
    서버 하나가 실패해도 나머지는 정상 기동되어야 한다.

    동시 기동으로 바꾼 뒤에도 실패 격리가 유지되는지 확인한다.
    """
    import dataclasses

    configs = dict(MCPClient.from_config().configs)
    # 존재하지 않는 모듈을 가리키는 서버를 하나 추가한다.
    sample = next(iter(configs.values()))
    configs["없는서버"] = dataclasses.replace(
        sample, name="없는서버", args=["-m", "app.mcp_servers.존재하지않는서버"]
    )

    client = MCPClient(configs, timeout=CONNECT_TIMEOUT)
    async with client:
        assert "없는서버" in client.failed_servers, "실패가 기록되지 않았다"
        # 정상 서버는 그대로 떠 있어야 한다.
        assert len(client.connected_servers) == len(configs) - 1


# ============================================================
# 2. 그래프 재사용
# ============================================================


async def test_graph_is_compiled_once(mcp_client: MCPClient) -> None:
    """같은 런타임에서는 그래프를 한 번만 컴파일해야 한다."""
    runtime = AgentRuntime.create(
        mcp_client,
        settings=load_settings(),
        llm=ScriptedLLM(score=90),
        event_bus=EventBus(),
    )

    assert runtime.compiled_graph is None, "초기에는 캐시가 비어 있어야 한다"

    first = get_graph(runtime)
    second = get_graph(runtime)

    assert first is second, "그래프가 매번 다시 컴파일되고 있다"
    assert runtime.compiled_graph is first


async def test_build_graph_still_creates_new_instances(mcp_client: MCPClient) -> None:
    """build_graph() 자체는 캐시 없이 매번 새로 만들어야 한다. (테스트 격리용)"""
    runtime = AgentRuntime.create(
        mcp_client,
        settings=load_settings(),
        llm=ScriptedLLM(score=90),
        event_bus=EventBus(),
    )
    assert build_graph(runtime) is not build_graph(runtime)


# ============================================================
# 3. 이벤트 기록 메모리 상한
# ============================================================


async def test_event_history_is_capped_per_run() -> None:
    """실행 1건의 이벤트가 상한을 넘으면 오래된 것부터 버려야 한다."""
    bus = EventBus(max_events_per_run=10, max_runs=5)

    for index in range(50):
        await bus.publish(AgentEvent(run_id="r1", type="tick", payload={"i": index}))

    history = bus.history("r1")
    assert len(history) == 10, "이벤트 상한이 적용되지 않았다 (메모리 누수)"
    # 최근 것이 남아야 한다.
    assert history[-1].payload["i"] == 49
    assert history[0].payload["i"] == 40


async def test_event_history_evicts_old_runs() -> None:
    """보관 실행 수가 상한을 넘으면 가장 오래된 실행 기록을 버려야 한다."""
    bus = EventBus(max_events_per_run=10, max_runs=3)

    for index in range(6):
        await bus.publish(AgentEvent(run_id=f"run-{index}", type="run_started"))

    assert bus.tracked_runs == 3, "실행 기록 상한이 적용되지 않았다 (메모리 누수)"
    # 오래된 실행은 비고, 최근 실행은 남아 있어야 한다.
    assert bus.history("run-0") == []
    assert bus.history("run-5") != []


async def test_event_bus_defaults_are_bounded() -> None:
    """기본 생성자도 상한이 걸려 있어야 한다. (기본값이 무한이면 의미 없음)"""
    bus = EventBus()
    assert bus._max_events_per_run == MAX_EVENTS_PER_RUN
    assert bus._max_runs == MAX_TRACKED_RUNS
    assert MAX_EVENTS_PER_RUN > 0
    assert MAX_TRACKED_RUNS > 0


async def test_subscriber_still_receives_recent_history() -> None:
    """상한을 걸어도 구독자는 남아 있는 기록을 받아야 한다."""
    bus = EventBus(max_events_per_run=5, max_runs=5)
    for index in range(3):
        await bus.publish(AgentEvent(run_id="r1", type="tick", payload={"i": index}))

    queue = bus.subscribe("r1")
    received = [queue.get_nowait().payload["i"] for _ in range(3)]
    assert received == [0, 1, 2]


# ============================================================
# 4. 실행 기록 메모리 상한
# ============================================================


async def test_run_records_are_capped(mcp_client: MCPClient) -> None:
    """끝난 실행이 상한을 넘으면 오래된 것부터 정리해야 한다."""
    runtime = AgentRuntime.create(
        mcp_client,
        settings=load_settings(),
        llm=ScriptedLLM(score=90),
        event_bus=EventBus(),
    )
    manager = RunManager(runtime, max_runs=3)

    # 그래프를 실제로 돌리지 않고 기록만 채운다. (완료 상태로)
    for index in range(10):
        record = RunRecord(run_id=f"done-{index}", user_request="요청")
        record.status = "completed"
        manager._runs[record.run_id] = record
        manager._evict_old_runs()

    assert len(manager.list_runs()) == 3, "실행 기록 상한이 적용되지 않았다"
    assert manager.get("done-0") is None
    assert manager.get("done-9") is not None


async def test_running_records_are_never_evicted(mcp_client: MCPClient) -> None:
    """진행 중인 실행은 상한을 넘어도 절대 버리지 않아야 한다."""
    runtime = AgentRuntime.create(
        mcp_client,
        settings=load_settings(),
        llm=ScriptedLLM(score=90),
        event_bus=EventBus(),
    )
    manager = RunManager(runtime, max_runs=2)

    for index in range(5):
        record = RunRecord(run_id=f"live-{index}", user_request="요청")
        record.status = "running"  # 전부 진행 중
        manager._runs[record.run_id] = record
        manager._evict_old_runs()

    # 하나도 버려지지 않아야 한다.
    assert len(manager.list_runs()) == 5
    for index in range(5):
        assert manager.get(f"live-{index}") is not None


async def test_eviction_prefers_finished_runs(mcp_client: MCPClient) -> None:
    """진행 중 실행과 끝난 실행이 섞여 있으면 끝난 것부터 버려야 한다."""
    runtime = AgentRuntime.create(
        mcp_client,
        settings=load_settings(),
        llm=ScriptedLLM(score=90),
        event_bus=EventBus(),
    )
    manager = RunManager(runtime, max_runs=2)

    live = RunRecord(run_id="live", user_request="요청")
    live.status = "running"
    done = RunRecord(run_id="done", user_request="요청")
    done.status = "completed"
    extra = RunRecord(run_id="extra", user_request="요청")
    extra.status = "completed"

    # 오래된 순: live → done → extra
    for record in (live, done, extra):
        manager._runs[record.run_id] = record
    manager._evict_old_runs()

    assert manager.get("live") is not None, "진행 중 실행이 버려졌다"
    assert manager.get("done") is None, "끝난 실행이 먼저 버려져야 한다"
    assert manager.get("extra") is not None


# ============================================================
# 5. 도구 조회 비용
# ============================================================


async def test_tool_lookup_is_constant_time(mcp_client: MCPClient) -> None:
    """도구 조회는 dict 조회여야 한다. (선형 탐색이면 도구가 늘수록 느려진다)"""
    from app.mcp_client.tool_registry import ToolRegistry

    registry = ToolRegistry(mcp_client)
    count = registry.refresh()
    assert count > 0

    name = registry.tools[0].qualified_name

    start = time.perf_counter()
    for _ in range(20_000):
        registry.get(name)
    elapsed = time.perf_counter() - start

    # 2만 회 조회가 1초를 넘으면 조회 경로에 무거운 작업이 섞인 것이다.
    assert elapsed < 1.0, f"도구 조회 2만 회에 {elapsed:.2f}초가 걸렸습니다"


# ============================================================
# 6. 동시 실행 안정성
# ============================================================


async def test_concurrent_tool_calls_do_not_interfere(mcp_client: MCPClient) -> None:
    """
    같은 MCP 세션에 동시 요청을 보내도 응답이 섞이지 않아야 한다.

    (JSON-RPC 요청 id 로 응답을 구분하므로 동시 호출이 안전해야 한다)
    """
    results: list[Any] = await asyncio.gather(
        *(
            mcp_client.call_tool("filesystem", "list_dir", {"path": "."})
            for _ in range(5)
        )
    )
    assert len(results) == 5
    for result in results:
        assert not result.is_error
        assert result.server == "filesystem"
        assert result.tool == "list_dir"


# ============================================================
# 7. 실제 화면 환경 대응 (실제 디스플레이에서 확인된 문제들)
# ============================================================


def test_gui_env_vars_are_passed_to_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    화면 관련 환경변수가 MCP 서버 프로세스로 전달되어야 한다.

    MCP SDK 의 기본 환경변수 허용 목록은 DISPLAY 를 걸러낸다.
    그대로 두면 부모에서는 캡처가 되는데 **screen 서버에서만 실패**한다.
    (실제 가상 디스플레이에서 확인된 문제)
    """
    from app.mcp_client.client import GUI_ENV_VARS, build_server_env

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setenv("XAUTHORITY", "/tmp/xauth-test")

    env = build_server_env()

    assert env.get("DISPLAY") == ":99", "DISPLAY 가 서버로 전달되지 않았다"
    assert env.get("XAUTHORITY") == "/tmp/xauth-test"
    # 목록에 X11 / Wayland / Windows 세션 변수가 모두 들어 있어야 한다.
    assert "DISPLAY" in GUI_ENV_VARS
    assert "WAYLAND_DISPLAY" in GUI_ENV_VARS
    assert "SESSIONNAME" in GUI_ENV_VARS


def test_gui_env_vars_absent_are_not_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    """설정되지 않은 환경변수를 빈 값으로 넣지 않아야 한다."""
    from app.mcp_client.client import build_server_env

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    env = build_server_env()

    assert "DISPLAY" not in env
    assert "WAYLAND_DISPLAY" not in env
    # 기본 주입 변수는 그대로 있어야 한다.
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_pyautogui_systemexit_becomes_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    PyAutoGUI 로드가 sys.exit() 로 죽어도 MCP 서버가 살아 있어야 한다.

    리눅스에서 tkinter 가 없으면 pyautogui 는 ImportError 가 아니라
    SystemExit 를 낸다. 이것을 놓치면 **서버 프로세스가 종료**되어
    도구 하나가 아니라 전체 기능이 사라진다.
    """
    import builtins

    from app.mcp_servers.automation_server import _load_pyautogui
    from app.mcp_servers.base_server import MCPToolError

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pyautogui":
            raise SystemExit("tkinter 없음")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(MCPToolError) as exc_info:
        _load_pyautogui()

    message = str(exc_info.value)
    assert "화면이 없는 환경" in message
    assert "SystemExit" in message


def test_pyautogui_keyboard_interrupt_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """사용자 중단(Ctrl+C)은 삼키지 않고 그대로 전달해야 한다."""
    import builtins

    from app.mcp_servers.automation_server import _load_pyautogui

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "pyautogui":
            raise KeyboardInterrupt
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(KeyboardInterrupt):
        _load_pyautogui()
