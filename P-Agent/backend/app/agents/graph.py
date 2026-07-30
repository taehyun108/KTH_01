"""
LangGraph StateGraph 구성.

6개 Agent 를 순서대로 연결하고, **Verifier → Retriever 피드백 루프**를 둔다.

    Planner → Perception → Executor → Retriever → Verifier → Generator → END
                                          ▲           │
                                          └───────────┘
                                        신뢰도 미달 시 재검색

각 노드 사이에는 **중단 검사**가 들어간다.
Kill Switch 가 눌리면 다음 노드로 넘어가지 않고 즉시 종료한다.
노드에서 예외가 발생해도 그래프 전체가 죽지 않고 상태에 오류를 기록한 뒤 종료한다.

무한 루프 방지
--------------
루프 진입 조건은 Verifier 가 채운 `retry_reason` 하나뿐이고,
Retriever 는 진입 즉시 그 값을 비운다. 회차 상한(`max_iterations`)과
검색어 중복 검사(`feedback.should_retry` / `select_new_queries`)가 더해져
3중으로 막히며, 그래도 남는 위험에 대비해 그래프 자체에
`recursion_limit` 을 회차 수에 맞춰 계산해 넣는다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents import (
    executor,
    generator,
    perception,
    planner,
    retriever,
    verifier,
)
from app.agents.runtime import AgentRuntime, KilledError
from app.agents.state import AgentState

#: 노드 실행 순서 (이름, 모듈)
AGENT_SEQUENCE: tuple[tuple[str, Any], ...] = (
    ("planner", planner),
    ("perception", perception),
    ("executor", executor),
    ("retriever", retriever),
    ("verifier", verifier),
    ("generator", generator),
)

NodeFunc = Callable[[AgentState], Awaitable[dict[str, Any]]]

#: 피드백 루프의 시작 노드 (되돌아갈지 판단하는 곳)
RETRY_SOURCE: str = "verifier"

#: 피드백 루프의 도착 노드 (다시 근거를 모으는 곳)
RETRY_TARGET: str = "retriever"

#: 재검색 1회당 추가로 방문하는 노드 수 (retriever → verifier, 그리고 라우터)
_NODES_PER_RETRY: int = 3

#: recursion_limit 여유분 (LangGraph 내부 단계 대비)
_RECURSION_BUFFER: int = 10


def recursion_limit_for(max_iterations: int) -> int:
    """
    회차 상한에 맞는 LangGraph `recursion_limit` 을 계산한다.

    재검색이 늘어나면 방문 노드 수도 늘어나므로, 상한을 고정값으로 두면
    `GraphRecursionError` 로 실행이 죽는다. 회차에 비례해 넉넉히 잡는다.
    """
    retries = max(0, max_iterations - 1)
    return len(AGENT_SEQUENCE) + retries * _NODES_PER_RETRY + _RECURSION_BUFFER


def _wrap_node(name: str, module: Any, runtime: AgentRuntime) -> NodeFunc:
    """
    Agent 모듈의 run() 을 LangGraph 노드로 감싼다.

    - 중단(Kill Switch) 요청을 처리한다.
    - 예외가 나도 그래프를 죽이지 않고 상태에 기록한다.
    """

    async def node(state: AgentState) -> dict[str, Any]:
        run_id = state.get("run_id", "")

        # 이미 종료된 실행이면 아무 것도 하지 않는다.
        if state.get("finished"):
            return {}

        try:
            return await module.run(state, runtime)
        except KilledError:
            await runtime.emit(run_id, "run_killed", step=name)
            return {
                "finished": True,
                "finish_reason": "killed",
                "notes": [f"'{name}' 단계에서 사용자가 실행을 중단했습니다."],
            }
        except Exception as exc:  # noqa: BLE001 - 한 노드의 실패로 전체를 죽이지 않는다
            message = f"'{name}' 단계에서 오류가 발생했습니다: {exc}"
            await runtime.emit(run_id, "step_error", step=name, error=str(exc))
            return {
                "finished": True,
                "finish_reason": "error",
                "error": message,
                "notes": [message],
            }

    node.__name__ = f"node_{name}"
    return node


def _make_router(next_node: str) -> Callable[[AgentState], str]:
    """
    다음 노드로 갈지 종료할지 결정하는 라우터를 만든다.

    상태가 `finished` 이면(중단/오류) 즉시 END 로 보낸다.
    """

    def route(state: AgentState) -> str:
        if state.get("finished"):
            return "end"
        return "continue"

    route.__name__ = f"route_to_{next_node}"
    return route


def _make_retry_router() -> Callable[[AgentState], str]:
    """
    Verifier 전용 라우터. (피드백 루프의 분기점)

    - 중단/오류      → END
    - `retry_reason` → Retriever 로 되돌아가 재검색
    - 그 외          → Generator 로 진행

    `retry_reason` 은 Retriever 가 진입 시 비우므로 같은 분기가 반복되지 않는다.
    """

    def route(state: AgentState) -> str:
        if state.get("finished"):
            return "end"
        if state.get("retry_reason"):
            return "retry"
        return "continue"

    route.__name__ = "route_verifier"
    return route


def build_graph(runtime: AgentRuntime) -> Any:
    """
    6개 Agent 를 연결한 그래프를 만들어 컴파일한다.

    Args:
        runtime: 모든 노드가 공유할 실행 런타임

    Returns:
        컴파일된 LangGraph (ainvoke 로 실행)
    """
    builder: StateGraph = StateGraph(AgentState)

    for name, module in AGENT_SEQUENCE:
        builder.add_node(name, _wrap_node(name, module, runtime))

    builder.add_edge(START, AGENT_SEQUENCE[0][0])

    # 노드 사이마다 중단 검사를 넣는다.
    for index, (name, _) in enumerate(AGENT_SEQUENCE):
        is_last = index == len(AGENT_SEQUENCE) - 1
        if is_last:
            builder.add_edge(name, END)
            continue

        next_name = AGENT_SEQUENCE[index + 1][0]

        if name == RETRY_SOURCE:
            # 피드백 루프: 신뢰도 미달이면 Retriever 로 되돌아간다.
            builder.add_conditional_edges(
                name,
                _make_retry_router(),
                {"retry": RETRY_TARGET, "continue": next_name, "end": END},
            )
            continue

        builder.add_conditional_edges(
            name,
            _make_router(next_name),
            {"continue": next_name, "end": END},
        )

    return builder.compile()


async def run_graph(
    runtime: AgentRuntime, state: AgentState
) -> AgentState:
    """
    그래프를 한 번 실행한다.

    Args:
        runtime: 실행 런타임
        state: `initial_state()` 로 만든 초기 상태

    Returns:
        최종 상태
    """
    graph = build_graph(runtime)

    # 재검색 회차에 맞춰 recursion_limit 을 계산한다.
    # (상태에 값이 없으면 설정값을 따른다)
    max_iterations = state.get("max_iterations") or runtime.settings.agent_max_iterations
    result: AgentState = await graph.ainvoke(
        state, config={"recursion_limit": recursion_limit_for(max_iterations)}
    )

    # 정상 완료 시 종료 사유를 채운다.
    if not result.get("finished"):
        result["finished"] = True
        result["finish_reason"] = "completed"
    return result
