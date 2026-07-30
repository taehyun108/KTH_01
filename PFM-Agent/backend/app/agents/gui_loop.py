"""
GUI 자동 조작 루프 로직 (OpenClaw 형 컴퓨터 조작 방식).

왜 루프인가
-----------
사람은 화면을 **보고 → 한 번 조작하고 → 결과를 다시 보고 → 다음을 결정**한다.
미리 만든 대본을 끝까지 밀어붙이지 않는다. 화면이 예상과 다르면 그때 판단을 바꾼다.

그래서 Executor 는 계획서를 순서대로 실행하지 않고 아래를 반복한다.

    1. 화면 인식  (screen.list_ui_elements) — 지금 화면에 무엇이 있는가
    2. 판단       (LLM)                     — 목표까지 다음 한 걸음은 무엇인가
    3. 조작       (automation.*)            — 그 한 걸음만 수행 (승인 게이트 통과)
    4. 관찰       → 1번으로 돌아감          — 조작 결과를 화면으로 다시 확인

이 모듈은 그 판단부(파싱·정지 조건)를 **순수 함수**로 모아 두어, 실제 화면이나
LLM 없이도 단독 테스트할 수 있게 한다.

🔴 폭주 방지 (4중 안전장치)
---------------------------
1. **조작 수 상한** — `GUI_MAX_STEPS` 를 넘으면 무조건 중단
2. **제자리 감지** — 같은 조작을 반복하면(화면이 안 바뀜) 중단
3. **승인 게이트** — 모든 조작은 사용자 승인 필요 (레지스트리가 강제)
4. **Kill Switch** — 매 조작 전 중단 여부 확인 (ESC)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

#: LLM 이 선택할 수 있는 조작 종류
CLICK = "click"
TYPE = "type"
KEY = "key"
OPEN_BROWSER = "open_browser"
DONE = "done"
GIVE_UP = "give_up"

#: 실제로 PC 를 건드리는 조작 (승인 게이트 대상)
ACTING_TYPES: frozenset[str] = frozenset({CLICK, TYPE, KEY, OPEN_BROWSER})

#: 루프를 끝내는 조작
TERMINAL_TYPES: frozenset[str] = frozenset({DONE, GIVE_UP})

#: 허용되는 모든 조작
VALID_TYPES: frozenset[str] = ACTING_TYPES | TERMINAL_TYPES

#: 같은 조작이 이 횟수만큼 연속되면 '제자리'로 판단한다.
STUCK_THRESHOLD: int = 3

#: 프롬프트에 넣을 조작 이력 최대 건수 (토큰 절약)
HISTORY_WINDOW: int = 8

#: 프롬프트에 넣을 화면 요소 최대 건수
ELEMENT_WINDOW: int = 40


SYSTEM_PROMPT = """당신은 사용자를 대신해 Windows PC 화면을 조작하는 담당자입니다.
현재 화면에서 읽은 요소 목록과 지금까지 한 조작을 보고, **목표에 가까워지는
다음 한 걸음만** 결정하세요.

선택할 수 있는 조작:
- {{"action": "click", "target": "누를 요소의 글자", "reason": "이유"}}
- {{"action": "type", "text": "입력할 내용", "reason": "이유"}}
- {{"action": "key", "key": "enter", "reason": "이유"}}
- {{"action": "open_browser", "url": "https://...", "reason": "이유"}}
- {{"action": "done", "reason": "목표를 달성한 근거"}}
- {{"action": "give_up", "reason": "더 진행할 수 없는 이유"}}

규칙:
- 한 번에 **조작 하나만** 답하세요. 여러 개를 한꺼번에 계획하지 마세요.
- `click` 의 `target` 은 **화면 요소 목록에 실제로 있는 글자**를 그대로 쓰세요.
- 목록에 없는 것을 누르려 하지 마세요. 없으면 `give_up` 을 선택하세요.
- 목표가 이미 달성됐으면 곧바로 `done` 을 선택하세요.
- 같은 조작을 반복하지 마세요. 화면이 바뀌지 않으면 다른 방법을 시도하세요.
- 최대 {max_steps}번까지만 조작할 수 있습니다. 남은 횟수를 고려하세요.
- 반드시 **JSON 객체 하나만** 답하세요. 설명을 덧붙이지 마세요."""


@dataclass(frozen=True)
class ActionDecision:
    """LLM 이 결정한 조작 한 건."""

    action: str
    """조작 종류 (click / type / key / open_browser / done / give_up)"""

    target: str = ""
    """click 대상 요소의 글자"""

    text: str = ""
    """type 으로 입력할 내용"""

    key: str = ""
    """key 로 누를 키 이름"""

    url: str = ""
    """open_browser 로 열 주소"""

    reason: str = ""
    """왜 이 조작을 선택했는지"""

    @property
    def is_terminal(self) -> bool:
        """루프를 끝내는 조작인지."""
        return self.action in TERMINAL_TYPES

    @property
    def is_acting(self) -> bool:
        """실제로 PC 를 건드리는 조작인지."""
        return self.action in ACTING_TYPES

    def signature(self) -> str:
        """
        '같은 조작인지' 판단할 때 쓰는 지문.

        이유(reason)는 매번 달라질 수 있으므로 제외한다.
        """
        return f"{self.action}|{self.target}|{self.text}|{self.key}|{self.url}".lower()

    def describe(self) -> str:
        """사용자에게 보여줄 한글 설명."""
        if self.action == CLICK:
            return f"'{self.target}' 클릭"
        if self.action == TYPE:
            return f"'{self.text}' 입력"
        if self.action == KEY:
            return f"{self.key} 키 입력"
        if self.action == OPEN_BROWSER:
            return f"브라우저로 {self.url} 열기"
        if self.action == DONE:
            return "작업 완료 판단"
        return "진행 중단 판단"


@dataclass
class LoopOutcome:
    """루프 종료 결과."""

    reason: str
    """종료 사유 (사용자에게 보여줄 한글)"""

    completed: bool = False
    """목표를 달성했다고 판단했는지"""

    steps: int = 0
    """실제로 수행한 조작 수"""

    history: list[str] = field(default_factory=list)
    """조작 이력"""


def parse_action(raw: str) -> ActionDecision | None:
    """
    LLM 응답에서 조작 결정을 추출한다.

    코드블록이나 앞뒤 설명이 섞여 와도 최대한 복구한다.
    형식이 끝까지 이해되지 않으면 None 을 반환해 호출부가 안전하게 멈추게 한다.
    """
    text = raw.strip()
    if not text:
        return None

    # ```json ... ``` 코드블록 제거
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    payload = _load_json_object(text)
    if payload is None:
        return None

    action = str(payload.get("action", "")).strip().lower()
    if action not in VALID_TYPES:
        return None

    return ActionDecision(
        action=action,
        target=str(payload.get("target", "")).strip(),
        text=str(payload.get("text", "")),
        key=str(payload.get("key", "")).strip(),
        url=str(payload.get("url", "")).strip(),
        reason=str(payload.get("reason", "")).strip(),
    )


def _load_json_object(text: str) -> dict[str, Any] | None:
    """문자열에서 JSON 객체 하나를 읽어낸다. (앞뒤 잡텍스트 허용)"""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 본문 중간에 박힌 { ... } 를 찾아 다시 시도한다.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_decision(
    decision: ActionDecision, elements: list[dict[str, Any]]
) -> str | None:
    """
    조작을 실제로 수행해도 되는지 검사한다.

    Returns:
        문제가 없으면 None, 있으면 사용자에게 보여줄 한글 사유
    """
    if decision.action == CLICK:
        if not decision.target:
            return "누를 대상이 비어 있어 클릭하지 않았습니다."
        if elements and not _target_exists(decision.target, elements):
            return (
                f"'{decision.target}' 이(가) 화면 요소 목록에 없어 클릭하지 않았습니다. "
                f"(엉뚱한 곳을 누르는 것을 막기 위한 안전 조치입니다)"
            )
    elif decision.action == TYPE:
        if not decision.text:
            return "입력할 내용이 비어 있어 입력하지 않았습니다."
    elif decision.action == KEY:
        if not decision.key:
            return "누를 키가 비어 있어 실행하지 않았습니다."
    elif decision.action == OPEN_BROWSER:
        if not decision.url:
            return "열 주소가 비어 있어 브라우저를 열지 않았습니다."

    return None


def _target_exists(target: str, elements: list[dict[str, Any]]) -> bool:
    """대상 글자가 화면 요소 목록에 있는지 확인한다. (부분 일치 허용)"""
    needle = _normalize(target)
    if not needle:
        return False
    for element in elements:
        haystack = _normalize(str(element.get("text", "")))
        if needle in haystack or haystack in needle:
            return True
    return False


def _normalize(text: str) -> str:
    """비교용 정규화. (공백 제거 + 소문자)"""
    return re.sub(r"\s+", "", text).lower()


def is_stuck(signatures: list[str], threshold: int = STUCK_THRESHOLD) -> bool:
    """
    같은 조작이 연속으로 반복되는지 확인한다.

    화면이 바뀌지 않는데 같은 곳을 계속 누르는 상황을 잡아낸다.
    (LLM 이 판단을 못 바꾸는 경우가 실제로 있으므로 코드로 막는다)
    """
    if len(signatures) < threshold:
        return False
    recent = signatures[-threshold:]
    return len(set(recent)) == 1


def format_elements(elements: list[dict[str, Any]], limit: int = ELEMENT_WINDOW) -> str:
    """화면 요소 목록을 프롬프트용 문자열로 만든다."""
    if not elements:
        return "(화면에서 인식된 요소가 없습니다)"

    lines: list[str] = []
    for element in elements[:limit]:
        text = str(element.get("text", "")).strip()
        if not text:
            continue
        lines.append(f"- \"{text}\" (좌표 {element.get('x')}, {element.get('y')})")

    if len(elements) > limit:
        lines.append(f"- ... 외 {len(elements) - limit}개 더 있음")

    return "\n".join(lines) or "(화면에서 인식된 요소가 없습니다)"


def build_prompt(
    goal: str,
    elements: list[dict[str, Any]],
    history: list[str],
    *,
    step: int,
    max_steps: int,
) -> str:
    """LLM 에게 보낼 판단 요청문을 만든다."""
    recent = history[-HISTORY_WINDOW:]
    history_text = (
        "\n".join(f"{index + 1}. {item}" for index, item in enumerate(recent))
        or "(아직 조작한 것이 없습니다)"
    )

    return (
        f"목표:\n{goal}\n\n"
        f"현재 화면에서 인식된 요소:\n{format_elements(elements)}\n\n"
        f"지금까지 한 조작:\n{history_text}\n\n"
        f"진행 상황: {step}/{max_steps}번째 조작을 결정하는 중입니다.\n"
        f"다음 조작 하나를 JSON 으로 답하세요."
    )
