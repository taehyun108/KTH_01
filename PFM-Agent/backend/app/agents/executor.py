"""
Executor Agent — 자연어 지시만으로 PC GUI 를 자동 조작한다.

두 가지 실행 방식
-----------------
**1) GUI 자동 조작 루프 (기본)** — 사람이 PC 를 쓰는 방식과 같다.

    화면 인식 → 판단(LLM) → 조작 1회 → 다시 화면 인식 → ...

  미리 만든 대본을 밀어붙이지 않고, **조작할 때마다 화면을 다시 보고**
  다음 한 걸음을 결정한다. 화면이 예상과 다르면 그때 판단을 바꾼다.
  판단 로직은 `app/agents/gui_loop.py` 참고.

**2) 계획 대본 실행 (대체 수단)** — LLM 을 쓸 수 없을 때.

  폐쇄망에서 P-GPT 가 응답하지 않거나 `GUI_LOOP_ENABLED=false` 인 경우,
  Planner 가 만든 계획 문장을 키워드로 해석해 순서대로 실행한다.
  적응력은 없지만 **아무것도 못 하는 상황을 피하기 위한** 경로다.

🔴 안전 원칙 (두 방식 모두 동일)
--------------------------------
1. automation 서버 도구는 **승인 게이트를 반드시 통과**해야 실행된다.
   (레지스트리가 강제하므로 이 파일에서 우회할 수 없다)
2. **화면을 못 본 상태에서는 좌표 기반 조작을 하지 않는다.**
   화면 인식이 실패했는데 클릭하면 엉뚱한 곳을 누를 수 있기 때문이다.
3. 조작 수에 상한을 둔다. (`GUI_MAX_STEPS` / `MAX_ACTIONS`)
4. 같은 조작이 반복되면(화면이 안 바뀜) 중단한다.
5. 매 조작 전에 Kill Switch 를 확인한다.
6. 도구 실행이 거절/실패해도 그래프는 멈추지 않고 사유를 기록한다.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents import gui_loop
from app.agents.gui_loop import ActionDecision, LoopOutcome
from app.agents.perception import needs_screen
from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState
from app.llm.base import ChatMessage, LLMError

STEP_NAME = "executor"

#: 화면 인식 실패를 나타내는 관찰 문구 (perception.py 와 맞춤)
_NO_SCREEN_MARKER = "화면 인식을 사용할 수 없어"

#: 한 실행에서 수행할 최대 조작 수 (폭주 방지)
MAX_ACTIONS: int = 10

#: URL 을 추출하는 정규식
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")

#: 조작 종류를 판단하는 키워드
_BROWSER_KEYWORDS = ("브라우저", "웹", "사이트", "접속", "홈페이지", "url", "http")
_CLICK_KEYWORDS = ("클릭", "누르", "선택", "버튼")
_TYPE_KEYWORDS = ("입력", "타이핑", "검색어", "적는다", "작성")


def extract_url(text: str) -> str | None:
    """계획 문장에서 URL 을 찾는다."""
    match = _URL_PATTERN.search(text)
    return match.group(0) if match else None


def classify_action(step_text: str) -> str:
    """
    계획 단계가 어떤 조작인지 분류한다.

    Returns:
        "browser" | "click" | "type" | "none"
    """
    lowered = step_text.lower()

    if extract_url(step_text) or any(word in lowered for word in _BROWSER_KEYWORDS):
        return "browser"
    if any(word in lowered for word in _CLICK_KEYWORDS):
        return "click"
    if any(word in lowered for word in _TYPE_KEYWORDS):
        return "type"
    return "none"


def extract_target(step_text: str) -> str:
    """
    클릭 대상 설명을 추출한다.

    '검색 버튼을 클릭한다' → '검색 버튼'
    """
    cleaned = re.sub(r"[을를]?\s*(클릭|누르|선택)\S*", "", step_text).strip()
    cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned).strip()
    return cleaned or step_text


async def _do_browser(
    step_text: str, state: AgentState, runtime: AgentRuntime
) -> tuple[str, dict[str, Any]]:
    """브라우저를 연다."""
    url = extract_url(step_text)
    if url is None:
        return (
            f"'{step_text}' 에서 접속할 주소를 찾지 못해 건너뛰었습니다.",
            {},
        )

    result = await runtime.call_tool(
        STEP_NAME, "automation__open_browser", {"url": url}, run_id=state["run_id"]
    )
    message = (
        f"브라우저로 {url} 을(를) 열었습니다."
        if result["ok"]
        else f"브라우저 열기 실패: {result['text']}"
    )
    return message, result["log"]


async def _do_click(
    step_text: str, state: AgentState, runtime: AgentRuntime
) -> tuple[str, list[dict[str, Any]]]:
    """UI 요소를 찾아 클릭한다. (화면 인식 → 좌표 → 클릭)"""
    logs: list[dict[str, Any]] = []
    target = extract_target(step_text)
    run_id = state["run_id"]

    # 1) 화면에서 요소 위치를 찾는다.
    found = await runtime.call_tool(
        STEP_NAME, "screen__find_ui_element", {"description": target}, run_id=run_id
    )
    logs.append(found["log"])

    if not found["ok"]:
        return f"'{target}' 을(를) 화면에서 찾지 못했습니다: {found['text']}", logs

    structured = found["structured"] or {}
    x, y = structured.get("x"), structured.get("y")
    if x is None or y is None:
        return f"'{target}' 의 좌표를 확인하지 못했습니다.", logs

    # 2) 찾은 좌표를 클릭한다. (승인 게이트 통과 필요)
    clicked = await runtime.call_tool(
        STEP_NAME, "automation__click", {"x": x, "y": y}, run_id=run_id
    )
    logs.append(clicked["log"])

    if clicked["ok"]:
        return f"'{target}' ({x}, {y}) 을(를) 클릭했습니다.", logs
    return f"'{target}' 클릭 실패: {clicked['text']}", logs


async def _do_type(
    step_text: str, state: AgentState, runtime: AgentRuntime
) -> tuple[str, dict[str, Any]]:
    """텍스트를 입력한다."""
    # 따옴표 안의 내용을 입력할 텍스트로 본다.
    match = re.search(r"[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]", step_text)
    if match is None:
        return (
            (
                f"'{step_text}' 에서 입력할 내용을 찾지 못해 건너뛰었습니다. "
                f"(입력할 내용을 따옴표로 감싸주세요)"
            ),
            {},
        )

    text = match.group(1)
    result = await runtime.call_tool(
        STEP_NAME, "automation__type_text", {"text": text}, run_id=state["run_id"]
    )
    message = (
        f"'{text}' 을(를) 입력했습니다."
        if result["ok"]
        else f"텍스트 입력 실패: {result['text']}"
    )
    return message, result["log"]


# ============================================================
# GUI 자동 조작 루프 (기본 경로)
# ============================================================


async def _observe_screen(
    state: AgentState, runtime: AgentRuntime, tool_log: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """
    현재 화면의 UI 요소를 읽어온다.

    Returns:
        (요소 목록, 실패 사유) — 실패 사유가 있으면 조작해서는 안 된다.
    """
    result = await runtime.call_tool(
        STEP_NAME,
        "screen__list_ui_elements",
        {},
        run_id=state["run_id"],
    )
    tool_log.append(result["log"])

    if not result["ok"]:
        return [], result["text"]

    structured = result["structured"] or {}
    elements = structured.get("elements", [])
    if not isinstance(elements, list):
        return [], "화면 요소 목록을 해석하지 못했습니다."
    return elements, None


async def _decide_action(
    state: AgentState,
    runtime: AgentRuntime,
    elements: list[dict[str, Any]],
    history: list[str],
    *,
    step: int,
    max_steps: int,
) -> tuple[ActionDecision | None, str]:
    """
    다음 조작 하나를 LLM 에게 판단받는다.

    Returns:
        (결정, 실패 사유) — 결정이 None 이면 루프를 멈춘다.
    """
    prompt = gui_loop.build_prompt(
        state["user_request"], elements, history, step=step, max_steps=max_steps
    )
    system = gui_loop.SYSTEM_PROMPT.format(max_steps=max_steps)

    try:
        response = await runtime.llm.chat(
            [ChatMessage(role="user", content=prompt)],
            system=system,
            max_tokens=1000,
        )
    except LLMError as exc:
        return None, f"다음 조작을 판단하지 못했습니다: {exc.message}"

    decision = gui_loop.parse_action(response.content)
    if decision is None:
        return None, "다음 조작 판단 결과를 이해하지 못해 조작을 중단했습니다."
    return decision, ""


async def _perform_action(
    decision: ActionDecision,
    state: AgentState,
    runtime: AgentRuntime,
    elements: list[dict[str, Any]],
    tool_log: list[dict[str, Any]],
) -> tuple[bool, str]:
    """
    결정된 조작 하나를 실제로 수행한다. (승인 게이트 통과 필요)

    Returns:
        (성공 여부, 결과 설명)
    """
    run_id = state["run_id"]

    if decision.action == gui_loop.OPEN_BROWSER:
        result = await runtime.call_tool(
            STEP_NAME,
            "automation__open_browser",
            {"url": decision.url},
            run_id=run_id,
        )
        tool_log.append(result["log"])
        return result["ok"], (
            f"브라우저로 {decision.url} 을(를) 열었습니다."
            if result["ok"]
            else f"브라우저 열기 실패: {result['text']}"
        )

    if decision.action == gui_loop.TYPE:
        result = await runtime.call_tool(
            STEP_NAME,
            "automation__type_text",
            {"text": decision.text},
            run_id=run_id,
        )
        tool_log.append(result["log"])
        return result["ok"], (
            f"'{decision.text}' 을(를) 입력했습니다."
            if result["ok"]
            else f"텍스트 입력 실패: {result['text']}"
        )

    if decision.action == gui_loop.KEY:
        result = await runtime.call_tool(
            STEP_NAME,
            "automation__key_press",
            {"key": decision.key},
            run_id=run_id,
        )
        tool_log.append(result["log"])
        return result["ok"], (
            f"{decision.key} 키를 눌렀습니다."
            if result["ok"]
            else f"키 입력 실패: {result['text']}"
        )

    # click — 요소 목록의 좌표를 그대로 쓴다. (다시 찾지 않아 왕복을 줄인다)
    coords = _coords_for(decision.target, elements)
    if coords is None:
        # 목록에서 좌표를 못 얻으면 화면 탐지 도구로 한 번 더 시도한다.
        found = await runtime.call_tool(
            STEP_NAME,
            "screen__find_ui_element",
            {"description": decision.target},
            run_id=run_id,
        )
        tool_log.append(found["log"])
        if not found["ok"]:
            return False, f"'{decision.target}' 을(를) 찾지 못했습니다: {found['text']}"
        structured = found["structured"] or {}
        x, y = structured.get("x"), structured.get("y")
        if x is None or y is None:
            return False, f"'{decision.target}' 의 좌표를 확인하지 못했습니다."
        coords = (int(x), int(y))

    clicked = await runtime.call_tool(
        STEP_NAME,
        "automation__click",
        {"x": coords[0], "y": coords[1]},
        run_id=run_id,
    )
    tool_log.append(clicked["log"])
    return clicked["ok"], (
        f"'{decision.target}' ({coords[0]}, {coords[1]}) 을(를) 클릭했습니다."
        if clicked["ok"]
        else f"'{decision.target}' 클릭 실패: {clicked['text']}"
    )


def _coords_for(
    target: str, elements: list[dict[str, Any]]
) -> tuple[int, int] | None:
    """요소 목록에서 대상 글자의 좌표를 찾는다. (부분 일치 허용)"""
    needle = re.sub(r"\s+", "", target).lower()
    if not needle:
        return None

    for element in elements:
        text = re.sub(r"\s+", "", str(element.get("text", ""))).lower()
        if not text:
            continue
        if needle in text or text in needle:
            x, y = element.get("x"), element.get("y")
            if x is not None and y is not None:
                return int(x), int(y)
    return None


async def _run_gui_loop(
    state: AgentState,
    runtime: AgentRuntime,
    executions: list[str],
    notes: list[str],
    tool_log: list[dict[str, Any]],
) -> LoopOutcome:
    """
    화면 인식 → 판단 → 조작 → 재확인을 목표 달성까지 반복한다.

    조작 수 상한 / 제자리 감지 / 승인 게이트 / Kill Switch 로 폭주를 막는다.
    """
    run_id = state["run_id"]
    max_steps = runtime.settings.gui_max_steps
    history: list[str] = []
    signatures: list[str] = []
    step = 0

    while step < max_steps:
        # 매 조작 전에 중단 여부를 확인한다. (ESC)
        runtime.ensure_alive(run_id)
        step += 1

        # --- 1) 화면 인식 ---
        elements, screen_error = await _observe_screen(state, runtime, tool_log)
        if screen_error is not None:
            message = (
                f"화면 상태를 확인할 수 없어 조작을 중단했습니다: {screen_error}"
            )
            notes.append(message)
            return LoopOutcome(reason=message, steps=step - 1, history=history)

        # --- 2) 판단 ---
        decision, decide_error = await _decide_action(
            state, runtime, elements, history, step=step, max_steps=max_steps
        )
        if decision is None:
            notes.append(decide_error)
            return LoopOutcome(reason=decide_error, steps=step - 1, history=history)

        await runtime.emit(
            run_id,
            "gui_action",
            step=STEP_NAME,
            index=step,
            max_steps=max_steps,
            action=decision.action,
            summary=decision.describe(),
            reason=decision.reason,
        )

        # --- 3) 종료 판단 ---
        if decision.is_terminal:
            completed = decision.action == gui_loop.DONE
            reason = decision.reason or decision.describe()
            message = (
                f"목표를 달성했다고 판단했습니다: {reason}"
                if completed
                else f"더 진행할 수 없어 중단했습니다: {reason}"
            )
            executions.append(message)
            if not completed:
                notes.append(message)
            return LoopOutcome(
                reason=message,
                completed=completed,
                steps=step - 1,
                history=history,
            )

        # --- 4) 조작 전 검증 (화면에 없는 것을 누르지 않는다) ---
        problem = gui_loop.validate_decision(decision, elements)
        if problem is not None:
            executions.append(problem)
            notes.append(problem)
            history.append(f"{decision.describe()} → 건너뜀 ({problem})")
            signatures.append(decision.signature())
            if gui_loop.is_stuck(signatures):
                return _stuck_outcome(step, history, notes)
            continue

        # --- 5) 제자리 감지 (같은 조작 반복) ---
        signatures.append(decision.signature())
        if gui_loop.is_stuck(signatures):
            return _stuck_outcome(step, history, notes)

        # --- 6) 조작 수행 (승인 게이트 통과 필요) ---
        ok, message = await _perform_action(
            decision, state, runtime, elements, tool_log
        )
        executions.append(message)
        if not ok:
            notes.append(message)
        history.append(f"{decision.describe()} → {'성공' if ok else '실패'}")

    message = (
        f"조작 횟수 상한({max_steps}회)에 도달해 중단했습니다. "
        f"목표가 완료되지 않았다면 요청을 더 구체적으로 나눠 다시 시도해 주세요."
    )
    notes.append(message)
    return LoopOutcome(reason=message, steps=max_steps, history=history)


def _stuck_outcome(
    step: int, history: list[str], notes: list[str]
) -> LoopOutcome:
    """같은 조작이 반복될 때의 종료 결과를 만든다."""
    message = (
        f"같은 조작이 {gui_loop.STUCK_THRESHOLD}번 반복되어 중단했습니다. "
        f"화면이 바뀌지 않았을 수 있습니다."
    )
    notes.append(message)
    return LoopOutcome(reason=message, steps=step, history=history)


# ============================================================
# 계획 대본 실행 (LLM 을 쓸 수 없을 때의 대체 경로)
# ============================================================


async def _run_plan_script(
    state: AgentState,
    runtime: AgentRuntime,
    executions: list[str],
    notes: list[str],
    tool_log: list[dict[str, Any]],
) -> None:
    """
    Planner 가 만든 계획 문장을 키워드로 해석해 순서대로 실행한다.

    화면을 다시 보지 않으므로 적응력은 없다. LLM 을 쓸 수 없을 때만 사용한다.
    """
    run_id = state["run_id"]
    action_count = 0

    for step_text in state.get("plan", []):
        if action_count >= MAX_ACTIONS:
            notes.append(
                f"조작 횟수 상한({MAX_ACTIONS}회)에 도달해 남은 단계를 건너뛰었습니다."
            )
            break

        runtime.ensure_alive(run_id)  # 각 조작 전에 중단 여부 확인
        action_type = classify_action(step_text)

        if action_type == "none":
            continue

        if action_type == "browser":
            message, log = await _do_browser(step_text, state, runtime)
            if log:
                tool_log.append(log)
        elif action_type == "click":
            message, logs = await _do_click(step_text, state, runtime)
            tool_log.extend(logs)
        else:  # type
            message, log = await _do_type(step_text, state, runtime)
            if log:
                tool_log.append(log)

        executions.append(message)
        if "실패" in message or "못했습니다" in message:
            notes.append(message)
        action_count += 1


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """자연어 지시에 따라 PC GUI 를 조작한다."""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)
    await runtime.emit(run_id, "step_started", step=STEP_NAME)

    plan = state.get("plan", [])
    user_request = state.get("user_request", "")
    observations = state.get("observations", [])

    executions: list[str] = []
    notes: list[str] = []
    tool_log: list[dict[str, Any]] = []
    gui_steps = 0

    # --- 1) 조작이 필요한 요청인지 확인 ---
    if not needs_screen(plan, user_request):
        executions.append("PC 조작이 필요하지 않아 실행 단계를 건너뛰었습니다.")
        await runtime.emit(run_id, "step_finished", step=STEP_NAME, skipped=True)
        return {
            "executions": executions,
            "notes": notes,
            "tool_log": tool_log,
            "gui_steps": 0,
        }

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
        return {
            "executions": executions,
            "notes": notes,
            "tool_log": tool_log,
            "gui_steps": 0,
        }

    # --- 3) GUI 자동 조작 루프 (기본 경로) ---
    if runtime.settings.gui_loop_enabled:
        outcome = await _run_gui_loop(state, runtime, executions, notes, tool_log)
        gui_steps = outcome.steps

        # 루프가 조작을 한 번도 못 했으면 계획 대본으로 한 번 더 시도한다.
        # (LLM 장애 등으로 판단이 불가능했던 경우 → 폐쇄망 대비)
        if gui_steps == 0 and not outcome.completed:
            notes.append(
                "화면을 보며 판단하는 방식을 쓸 수 없어 계획 순서대로 실행합니다."
            )
            await _run_plan_script(state, runtime, executions, notes, tool_log)
    else:
        # 설정으로 루프를 껐으면 계획 대본만 실행한다.
        notes.append(
            "GUI 자동 조작 루프가 꺼져 있어(GUI_LOOP_ENABLED=false) "
            "계획 순서대로 실행합니다."
        )
        await _run_plan_script(state, runtime, executions, notes, tool_log)

    if not executions:
        executions.append("수행할 PC 조작을 찾지 못했습니다.")

    await runtime.emit(
        run_id,
        "step_finished",
        step=STEP_NAME,
        executions=executions,
        gui_steps=gui_steps,
    )
    return {
        "executions": executions,
        "notes": notes,
        "tool_log": tool_log,
        "gui_steps": gui_steps,
    }
