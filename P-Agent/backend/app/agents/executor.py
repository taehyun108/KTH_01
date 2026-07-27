"""
Executor Agent — 계획에 따라 PC 를 조작한다.

`automation` MCP 서버의 도구를 사용한다. (STEP 6 에서 실제 구현 예정)

🔴 안전 원칙
------------
1. automation 서버의 도구는 **승인 게이트를 반드시 통과**해야 실행된다.
   (레지스트리가 강제하므로 이 파일에서 우회할 수 없다)
2. 화면 인식이 실패한 상태에서는 **좌표 기반 조작을 시도하지 않는다.**
   화면을 못 보는 상태로 클릭하면 엉뚱한 곳을 누를 수 있기 때문이다.
3. 도구 실행이 거절/실패해도 그래프는 멈추지 않고 사유를 기록한다.
"""

from __future__ import annotations

from typing import Any

from app.agents.perception import needs_screen
from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState

STEP_NAME = "executor"

#: 화면 인식 실패를 나타내는 관찰 문구
_NO_SCREEN_MARKER = "화면 인식을 사용할 수 없어"


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """계획에 따라 PC 조작을 수행한다."""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)
    await runtime.emit(run_id, "step_started", step=STEP_NAME)

    plan = state.get("plan", [])
    user_request = state.get("user_request", "")
    observations = state.get("observations", [])

    executions: list[str] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []

    # --- 1) 조작이 필요한 요청인지 확인 ---
    if not needs_screen(plan, user_request):
        executions.append("PC 조작이 필요하지 않아 실행 단계를 건너뛰었습니다.")
        await runtime.emit(run_id, "step_finished", step=STEP_NAME, skipped=True)
        return {"executions": executions, "notes": notes, "tool_log": tool_log}

    # --- 2) 화면을 못 본 상태에서는 조작하지 않는다 (안전) ---
    screen_unavailable = any(_NO_SCREEN_MARKER in obs for obs in observations)
    if screen_unavailable:
        message = (
            "화면 상태를 확인할 수 없어 PC 조작을 수행하지 않았습니다. "
            "(잘못된 위치를 클릭하는 것을 막기 위한 안전 조치입니다)"
        )
        executions.append(message)
        notes.append(message)
        await runtime.emit(
            run_id, "step_finished", step=STEP_NAME, skipped=True, reason="화면 인식 불가"
        )
        return {"executions": executions, "notes": notes, "tool_log": tool_log}

    # --- 3) 실제 조작 (승인 게이트 통과 필요) ---
    # STEP 6 에서 Perception 결과의 좌표를 이용한 반복 조작 루프로 확장한다.
    result = await runtime.call_tool(
        STEP_NAME,
        "automation__open_browser",
        {"url": "about:blank"},
        run_id=run_id,
    )
    tool_log.append(result["log"])

    if result["ok"]:
        executions.append(f"브라우저 실행 완료: {result['text']}")
    else:
        executions.append("PC 조작을 수행하지 못했습니다.")
        notes.append(f"PC 조작 실패: {result['text']}")

    await runtime.emit(run_id, "step_finished", step=STEP_NAME, executions=executions)
    return {"executions": executions, "notes": notes, "tool_log": tool_log}
