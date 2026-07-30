"""
PFM-Agent 성능 측정 스크립트.

최적화가 실제로 적용되어 있는지 **회사 PC 에서 직접 확인**하기 위한 도구다.
LLM 을 호출하지 않으므로 인터넷·P-GPT 없이도 실행할 수 있다.

실행:
    cd backend
    uv run python ../scripts/benchmark.py

측정 항목
---------
1. MCP 서버 기동 / 종료 시간 (동시 처리가 적용됐는지)
2. 그래프 컴파일 비용과 캐시 효과
3. 도구 조회 처리량
4. RAG 키워드 검색 처리량
5. 이벤트 버스 처리량과 메모리 상한 동작
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# 프로젝트 경로 설정 (절대경로 하드코딩 금지)
#   이 파일: <루트>/scripts/benchmark.py
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
BACKEND_DIR: Path = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

#: 반복 측정 횟수 (편차를 줄이기 위해 평균을 사용)
REPEAT: int = 3


@dataclass
class Result:
    """측정 결과 한 건."""

    name: str
    value: str
    note: str = ""


def _print_header(title: str) -> None:
    """구획 제목을 출력한다."""
    print()
    print(f"  {title}")
    print("  " + "-" * 54)


def _print_result(result: Result) -> None:
    """측정 결과 한 줄을 출력한다."""
    print(f"    {result.name:<28} {result.value:>14}  {result.note}")


# ============================================================
# 1. MCP 서버 기동 / 종료
# ============================================================


async def bench_mcp_lifecycle() -> list[Result]:
    """MCP 서버 기동·종료 시간을 측정한다."""
    from app.mcp_client.client import MCPClient

    connect_times: list[float] = []
    close_times: list[float] = []
    servers = 0
    tools = 0

    for _ in range(REPEAT):
        client = MCPClient.from_config()
        start = time.perf_counter()
        await client.connect()
        connected = time.perf_counter()
        servers = len(client.connected_servers)
        tools = client.total_tool_count()
        await client.aclose()
        closed = time.perf_counter()

        connect_times.append(connected - start)
        close_times.append(closed - connected)

    avg_connect = sum(connect_times) / len(connect_times)
    avg_close = sum(close_times) / len(close_times)

    # 서버 1개당 시간이 전체와 비슷하면 동시 기동이 적용된 것이다.
    per_server = avg_connect / servers if servers else 0.0

    return [
        Result("서버 기동(전체)", f"{avg_connect:.3f}s", f"서버 {servers}개 / 도구 {tools}개"),
        Result("서버 기동(1개 환산)", f"{per_server:.3f}s", "동시 기동이면 전체와 비슷"),
        Result("서버 종료(전체)", f"{avg_close:.3f}s", ""),
    ]


# ============================================================
# 2. 그래프 컴파일 / 캐시
# ============================================================


async def bench_graph() -> list[Result]:
    """그래프 컴파일 비용과 캐시 효과를 측정한다."""
    from app.agents.graph import build_graph, get_graph

    class _Stub:
        """컴파일만 하므로 실제 런타임은 필요 없다."""

        compiled_graph = None

    rounds = 20

    start = time.perf_counter()
    for _ in range(rounds):
        build_graph(_Stub())
    build_elapsed = (time.perf_counter() - start) / rounds

    runtime = _Stub()
    get_graph(runtime)  # 첫 호출로 캐시 채우기
    start = time.perf_counter()
    for _ in range(rounds):
        get_graph(runtime)
    cached_elapsed = (time.perf_counter() - start) / rounds

    speedup = build_elapsed / cached_elapsed if cached_elapsed else 0.0

    return [
        Result("그래프 컴파일(1회)", f"{build_elapsed * 1000:.2f}ms", "캐시 없을 때"),
        Result("그래프 캐시 조회", f"{cached_elapsed * 1_000_000:.2f}µs", f"약 {speedup:,.0f}배 빠름"),
    ]


# ============================================================
# 3. 도구 조회
# ============================================================


async def bench_tool_lookup() -> list[Result]:
    """도구 조회 처리량을 측정한다."""
    from app.mcp_client.client import MCPClient
    from app.mcp_client.tool_registry import ToolRegistry

    client = MCPClient.from_config()
    async with client:
        registry = ToolRegistry(client)
        count = registry.refresh()
        name = registry.tools[0].qualified_name

        rounds = 50_000
        start = time.perf_counter()
        for _ in range(rounds):
            registry.get(name)
        elapsed = time.perf_counter() - start

    per_second = rounds / elapsed if elapsed else 0.0
    return [
        Result("도구 조회", f"{per_second / 1_000_000:.2f}M/s", f"등록 도구 {count}개"),
    ]


# ============================================================
# 4. RAG 키워드 검색
# ============================================================


async def bench_rag_search() -> list[Result]:
    """모델 없이 동작하는 키워드 검색 처리량을 측정한다."""
    import tempfile

    from app.rag.vector_store import VectorStore

    with tempfile.TemporaryDirectory() as temp:
        store = VectorStore(
            data_dir=Path(temp), model_path=Path(temp) / "없는모델"
        )
        # 문서 색인
        docs = 50
        start = time.perf_counter()
        for index in range(docs):
            store.add_text(
                f"정책{index}.md",
                f"소듐이온배터리 정책 동향 {index}번 문서. "
                f"리튬 대비 원가가 낮아 ESS 분야에서 주목받고 있다.",
            )
        index_elapsed = time.perf_counter() - start

        rounds = 200
        start = time.perf_counter()
        for _ in range(rounds):
            store.search("소듐이온배터리 원가", top_k=5)
        search_elapsed = time.perf_counter() - start

        method = store.method

    return [
        Result("문서 색인", f"{index_elapsed / docs * 1000:.2f}ms", f"문서 {docs}건 기준"),
        Result("검색(1회)", f"{search_elapsed / rounds * 1000:.2f}ms", f"방식: {method}"),
    ]


# ============================================================
# 5. 이벤트 버스
# ============================================================


async def bench_event_bus() -> list[Result]:
    """이벤트 발행 처리량과 메모리 상한 동작을 확인한다."""
    from app.agents.runtime import (
        MAX_EVENTS_PER_RUN,
        MAX_TRACKED_RUNS,
        AgentEvent,
        EventBus,
    )

    bus = EventBus()
    rounds = 20_000

    start = time.perf_counter()
    for index in range(rounds):
        await bus.publish(
            AgentEvent(run_id="bench", type="tick", payload={"i": index})
        )
    elapsed = time.perf_counter() - start

    kept = len(bus.history("bench"))
    per_second = rounds / elapsed if elapsed else 0.0

    # 실행 기록 상한도 실제로 동작하는지 확인한다.
    overflow = EventBus(max_events_per_run=5, max_runs=3)
    for index in range(20):
        await overflow.publish(AgentEvent(run_id=f"r{index}", type="tick"))

    return [
        Result("이벤트 발행", f"{per_second / 1000:.1f}k/s", ""),
        Result(
            "이벤트 보관 상한",
            f"{kept}건",
            f"{rounds:,}건 발행 → 상한 {MAX_EVENTS_PER_RUN:,}건 유지",
        ),
        Result(
            "실행 보관 상한",
            f"{overflow.tracked_runs}건",
            f"20건 발생 → 상한 3건 유지 (기본 {MAX_TRACKED_RUNS}건)",
        ),
    ]


# ============================================================
# 실행
# ============================================================


BENCHMARKS: tuple[tuple[str, object], ...] = (
    ("1. MCP 서버 생명주기 (동시 기동/종료)", bench_mcp_lifecycle),
    ("2. LangGraph 컴파일 / 캐시", bench_graph),
    ("3. MCP 도구 조회", bench_tool_lookup),
    ("4. 사내 문서 검색 (RAG, 모델 없이)", bench_rag_search),
    ("5. 이벤트 버스 / 메모리 상한", bench_event_bus),
)


async def main() -> int:
    """전체 벤치마크를 실행한다."""
    print("=" * 60)
    print("  PFM-Agent 성능 측정")
    print(f"  (각 항목 {REPEAT}회 평균 / LLM 호출 없음)")
    print("=" * 60)

    failures = 0

    for title, benchmark in BENCHMARKS:
        _print_header(title)
        try:
            results = await benchmark()  # type: ignore[operator]
            for result in results:
                _print_result(result)
        except Exception as exc:  # noqa: BLE001 - 한 항목 실패로 전체를 멈추지 않는다
            failures += 1
            print(f"    [실패] {type(exc).__name__}: {exc}")

    print()
    print("=" * 60)
    if failures:
        print(f"  ⚠️  {failures}개 항목을 측정하지 못했습니다.")
    else:
        print("  ✅ 모든 항목을 측정했습니다.")
    print("=" * 60)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
