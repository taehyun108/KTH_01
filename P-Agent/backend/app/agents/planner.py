"""
Planner Agent — 사용자 요청을 실행 계획으로 분해한다.

입력: user_request
출력: plan (단계별 한 줄 설명 목록)

LLM 호출은 반드시 `runtime.llm` (LLMClient 팩토리로 생성된 인스턴스)만 사용한다.
LLM 호출이 실패해도 그래프가 멈추지 않도록 기본 계획으로 대체한다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState
from app.llm.base import ChatMessage, LLMError

STEP_NAME = "planner"

#: 계획 단계 최대 개수 (너무 길면 실행이 산만해진다)
MAX_PLAN_STEPS = 8

SYSTEM_PROMPT = """당신은 PC 업무 자동화 에이전트의 계획 수립 담당자입니다.
사용자의 요청을 실행 가능한 단계로 나누세요.

사용 가능한 도구 종류:
{tool_summary}

규칙:
- 최대 {max_steps}개 단계로 나눕니다.
- 각 단계는 한 문장으로 간결하게 작성합니다.
- 반드시 JSON 배열 형식으로만 답합니다. 예: ["1단계 설명", "2단계 설명"]
- 설명이나 인사말을 덧붙이지 마세요."""


def _parse_plan(raw: str) -> list[str]:
    """
    LLM 응답에서 계획 목록을 추출한다.

    JSON 배열이 아니어도 최대한 복구한다. (모델이 코드블록을 붙이는 경우 등)
    """
    text = raw.strip()

    # ```json ... ``` 코드블록 제거
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            steps = [str(item).strip() for item in parsed if str(item).strip()]
            return steps[:MAX_PLAN_STEPS]
    except json.JSONDecodeError:
        pass

    # JSON 파싱 실패 시: 줄 단위로 분해하고 목록 기호를 제거한다.
    lines: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    return lines[:MAX_PLAN_STEPS]


def _tool_summary(runtime: AgentRuntime) -> str:
    """등록된 도구를 서버 단위로 요약해 프롬프트에 넣는다."""
    by_server: dict[str, list[str]] = {}
    for tool in runtime.registry.tools:
        by_server.setdefault(tool.server, []).append(tool.name)
    return "\n".join(
        f"- {server}: {', '.join(names)}" for server, names in sorted(by_server.items())
    )


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """실행 계획을 세운다."""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)
    await runtime.emit(run_id, "step_started", step=STEP_NAME)

    user_request = state["user_request"]
    notes: list[str] = []

    system = SYSTEM_PROMPT.format(
        tool_summary=_tool_summary(runtime), max_steps=MAX_PLAN_STEPS
    )

    try:
        response = await runtime.llm.chat(
            [ChatMessage(role="user", content=user_request)],
            system=system,
            max_tokens=2000,
        )
        plan = _parse_plan(response.content)
    except LLMError as exc:
        # LLM 을 못 쓰는 상황(키 미설정/사내망 단절)에서도 진행은 가능해야 한다.
        plan = []
        notes.append(f"계획 수립에 LLM 을 사용하지 못했습니다: {exc.message}")

    if not plan:
        plan = [f"요청 처리: {user_request}"]
        notes.append("세부 계획을 만들지 못해 단일 단계로 진행합니다.")

    await runtime.emit(run_id, "step_finished", step=STEP_NAME, plan=plan)
    return {"plan": plan, "notes": notes}
