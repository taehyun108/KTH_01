"""
Verifier Agent — 수집한 근거의 신뢰도를 평가한다.

산출: confidence (0~100) + verification (근거와 함께 한 문장 설명)

STEP 7 에서 추가될 항목:
  - 개인정보 마스킹 (app/security/masking.py)
  - 화이트리스트 도메인 필터 (app/config/whitelist.json)

현재는 규칙 기반 기본 점수 + LLM 검토를 결합한다.
LLM 을 쓸 수 없으면 규칙 기반 점수만으로 동작한다. (폐쇄망 대비)
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState
from app.llm.base import ChatMessage, LLMError

STEP_NAME = "verifier"

#: 근거가 전혀 없을 때의 신뢰도
NO_EVIDENCE_SCORE = 20

#: 근거 1건당 가산점
PER_EVIDENCE_SCORE = 15

#: 규칙 기반 점수 상한
RULE_SCORE_CAP = 70

SYSTEM_PROMPT = """당신은 보고서 근거를 검토하는 검증 담당자입니다.
주어진 근거 자료가 사용자 요청에 답하기에 충분한지 평가하세요.

반드시 아래 형식으로만 답하세요:
점수: <0에서 100 사이 정수>
사유: <한 문장>"""


def rule_based_score(evidence_count: int, has_local_only: bool) -> int:
    """
    근거 개수 기반 기본 점수.

    - 근거가 없으면 낮은 점수
    - 근거가 많을수록 가산 (상한 있음)
    - 사내 RAG 없이 로컬 파일만 있으면 소폭 감점
    """
    if evidence_count == 0:
        return NO_EVIDENCE_SCORE
    score = min(RULE_SCORE_CAP, 30 + evidence_count * PER_EVIDENCE_SCORE)
    if has_local_only:
        score -= 5
    return max(0, min(100, score))


def _parse_llm_score(raw: str) -> tuple[int | None, str]:
    """LLM 응답에서 '점수:'와 '사유:'를 추출한다."""
    score: int | None = None
    reason = ""

    match = re.search(r"점수\s*[:：]\s*(\d{1,3})", raw)
    if match:
        value = int(match.group(1))
        if 0 <= value <= 100:
            score = value

    reason_match = re.search(r"사유\s*[:：]\s*(.+)", raw)
    if reason_match:
        reason = reason_match.group(1).strip()

    return score, reason


async def run(state: AgentState, runtime: AgentRuntime) -> dict[str, Any]:
    """근거를 검증하고 신뢰도 점수를 매긴다."""
    run_id = state["run_id"]
    runtime.ensure_alive(run_id)
    await runtime.emit(run_id, "step_started", step=STEP_NAME)

    evidences = state.get("evidences", [])
    notes: list[str] = []

    has_local_only = bool(evidences) and all(
        item.get("origin") != "rag" for item in evidences
    )
    score = rule_based_score(len(evidences), has_local_only)
    reason = f"근거 자료 {len(evidences)}건을 기준으로 평가했습니다."

    # LLM 이 사용 가능하면 검토 결과를 반영한다.
    if evidences:
        excerpt = "\n\n".join(
            f"[출처: {item['source']}]\n{item['content'][:800]}" for item in evidences[:5]
        )
        prompt = (
            f"사용자 요청:\n{state['user_request']}\n\n"
            f"수집된 근거:\n{excerpt}"
        )
        try:
            response = await runtime.llm.chat(
                [ChatMessage(role="user", content=prompt)],
                system=SYSTEM_PROMPT,
                max_tokens=1000,
            )
            llm_score, llm_reason = _parse_llm_score(response.content)
            if llm_score is not None:
                # 규칙 점수와 LLM 점수의 평균을 사용해 한쪽 편향을 줄인다.
                score = round((score + llm_score) / 2)
            if llm_reason:
                reason = llm_reason
        except LLMError as exc:
            notes.append(f"신뢰도 검토에 LLM 을 사용하지 못했습니다: {exc.message}")

    verification = f"신뢰도 {score}점 - {reason}"
    if score < 50:
        notes.append(
            "근거가 부족해 신뢰도가 낮습니다. 보고서 내용을 반드시 사람이 검토하세요."
        )

    await runtime.emit(
        run_id, "step_finished", step=STEP_NAME, confidence=score, reason=reason
    )
    return {"confidence": score, "verification": verification, "notes": notes}
