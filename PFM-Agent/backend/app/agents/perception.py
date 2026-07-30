"""
Perception Agent — 화면 상태를 인식한다.

`screen` MCP 서버의 도구를 사용한다. (STEP 6 에서 실제 구현 예정)

계획에 PC 화면 조작이 필요 없으면 화면 인식을 건너뛴다.
(불필요한 캡처로 시간과 토큰을 낭비하지 않기 위함)
"""

from __future__ import annotations

from typing import Any

from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState

STEP_NAME = "perception"

#: 화면 인식이 필요하다고 판단하는 계획 키워드
SCREEN_KEYWORDS = (
    "화면",
    "클릭",
    "브라우저",
    "웹",
    "검색창",
    "입력",
    "버튼",
    "캡처",
    "스크린",
    "실행",
)


def needs_screen(plan: list[str], user_request: str) -> bool:
    """계획이나 요청에 화면 조작이 포함되는지 판단한다."""
    haystack = " ".join(plan) + " " + user_request
    return any(keyword in haystack for keyword in SCREEN_KEYWORDS)


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """화면을 인식한다."""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)
    await runtime.emit(run_id, "step_started", step=STEP_NAME)

    plan = state.get("plan", [])
    user_request = state.get("user_request", "")

    observations: list[str] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    if not needs_screen(plan, user_request):
        observations.append("화면 조작이 필요하지 않아 화면 인식을 건너뛰었습니다.")
        await runtime.emit(
            run_id, "step_finished", step=STEP_NAME, skipped=True
        )
        return {"observations": observations, "notes": notes, "tool_log": tool_log}

    # screen MCP 서버를 통해 화면을 캡처한다. (Agent 는 직접 함수를 호출하지 않는다)
    result = await runtime.call_tool(
        STEP_NAME, "screen__capture_screen", {}, run_id=run_id
    )
    tool_log.append(result["log"])

    if result["ok"]:
        observations.append(f"화면 캡처 완료: {result['text']}")
    else:
        # STEP 6 이전에는 스텁이므로 실패가 정상이다. 진행을 막지 않는다.
        observations.append("화면 인식을 사용할 수 없어 화면 정보 없이 진행합니다.")
        notes.append(f"화면 인식 불가: {result['text']}")

    await runtime.emit(
        run_id, "step_finished", step=STEP_NAME, observations=observations
    )
    return {"observations": observations, "notes": notes, "tool_log": tool_log}
