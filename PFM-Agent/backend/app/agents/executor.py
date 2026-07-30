"""
Executor Agent — 계획에 따라 PC 를 조작한다. (STEP 6 구현)

동작 흐름
---------
1. 계획에서 조작이 필요한 단계를 골라낸다.
2. 각 단계마다:
   a. Perception 결과(화면 캡처)를 바탕으로 대상 UI 요소를 찾는다.
   b. 좌표를 얻으면 클릭/입력을 수행한다. (승인 게이트 통과 필요)
   c. 실패하면 사유를 기록하고 다음 단계로 넘어간다.

🔴 안전 원칙
------------
1. automation 서버 도구는 **승인 게이트를 반드시 통과**해야 실행된다.
   (레지스트리가 강제하므로 이 파일에서 우회할 수 없다)
2. **화면을 못 본 상태에서는 좌표 기반 조작을 하지 않는다.**
   화면 인식이 실패했는데 클릭하면 엉뚱한 곳을 누를 수 있기 때문이다.
3. 한 실행에서 수행할 조작 수에 상한을 둔다. (무한 루프 방지)
4. 도구 실행이 거절/실패해도 그래프는 멈추지 않고 사유를 기록한다.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.perception import needs_screen
from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState

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

    # --- 3) 계획 단계별로 조작을 수행한다 ---
    action_count = 0
    for step_text in plan:
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

    if not executions:
        executions.append("계획에서 수행할 PC 조작을 찾지 못했습니다.")

    await runtime.emit(run_id, "step_finished", step=STEP_NAME, executions=executions)
    return {"executions": executions, "notes": notes, "tool_log": tool_log}
