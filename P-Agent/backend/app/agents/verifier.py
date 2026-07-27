"""
Verifier Agent — 수집한 근거의 신뢰도를 평가한다. (STEP 7 구현)

산출: confidence (0~100) + verification (사유 설명)

검증 항목
---------
1. **출처 신뢰도**  : 사내 RAG > 로컬 파일 > 웹
2. **화이트리스트** : 허용되지 않은 도메인 출처는 근거에서 제외
3. **개인정보**     : 근거에 개인정보가 있으면 마스킹하고 경고
4. **LLM 검토**     : 근거가 질문에 답하기 충분한지 판단 (가능한 경우)

신뢰도가 낮으면 보고서에 "사람이 반드시 검토하라"는 경고를 남긴다.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.runtime import AgentRuntime
from app.agents.state import AgentState, Evidence
from app.llm.base import ChatMessage, LLMError
from app.security.masking import mask_text
from app.security.whitelist import check_url

STEP_NAME = "verifier"

#: 근거가 전혀 없을 때의 신뢰도
NO_EVIDENCE_SCORE = 20

#: 근거 1건당 가산점
PER_EVIDENCE_SCORE = 15

#: 규칙 기반 점수 상한
RULE_SCORE_CAP = 70

#: 신뢰도가 이 값 미만이면 사람 검토 경고를 남긴다.
LOW_CONFIDENCE_THRESHOLD = 50

#: 출처가 웹 주소인지 판단
_URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

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


def is_web_source(source: str) -> bool:
    """출처가 웹 주소인지 확인한다."""
    return bool(_URL_PATTERN.match(source.strip()))


def filter_by_whitelist(
    evidences: list[Evidence],
) -> tuple[list[Evidence], list[str]]:
    """
    화이트리스트에 없는 웹 출처를 근거에서 제외한다.

    사내 문서·로컬 파일은 웹 주소가 아니므로 검사 대상이 아니다.

    Returns:
        (통과한 근거, 제외 사유 목록)
    """
    kept: list[Evidence] = []
    rejected: list[str] = []

    for evidence in evidences:
        source = evidence.get("source", "")
        if not is_web_source(source):
            kept.append(evidence)
            continue

        allowed, reason = check_url(source)
        if allowed:
            kept.append(evidence)
        else:
            rejected.append(f"근거 제외 ({source}): {reason.splitlines()[0]}")

    return kept, rejected


def mask_evidences(evidences: list[Evidence]) -> tuple[list[Evidence], int]:
    """
    근거 본문의 개인정보를 가린다.

    Returns:
        (마스킹된 근거, 마스킹 건수)
    """
    masked_list: list[Evidence] = []
    total = 0

    for evidence in evidences:
        masked = mask_text(evidence.get("content", ""))
        total += masked.total
        masked_list.append(
            Evidence(
                source=evidence.get("source", ""),
                content=masked.text,
                origin=evidence.get("origin", ""),
            )
        )

    return masked_list, total


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

    raw_evidences = state.get("evidences", [])
    notes: list[str] = []

    # --- 1) 화이트리스트 필터 ---
    evidences, rejected = filter_by_whitelist(raw_evidences)
    notes.extend(rejected)
    if rejected:
        await runtime.emit(
            run_id, "evidence_filtered", step=STEP_NAME, rejected=len(rejected)
        )

    # --- 2) 개인정보 마스킹 ---
    evidences, masked_count = mask_evidences(evidences)
    if masked_count:
        message = (
            f"근거 자료에서 개인정보 {masked_count}건을 가렸습니다. "
            f"보고서에도 가려진 상태로 반영됩니다."
        )
        notes.append(message)
        await runtime.emit(
            run_id, "privacy_masked", step=STEP_NAME, count=masked_count
        )

    # --- 3) 규칙 기반 점수 ---
    has_local_only = bool(evidences) and all(
        item.get("origin") != "rag" for item in evidences
    )
    score = rule_based_score(len(evidences), has_local_only)
    reason = f"근거 자료 {len(evidences)}건을 기준으로 평가했습니다."

    # --- 4) LLM 검토 (가능한 경우) ---
    if evidences:
        excerpt = "\n\n".join(
            f"[출처: {item['source']}]\n{item['content'][:800]}" for item in evidences[:5]
        )
        prompt = f"사용자 요청:\n{state['user_request']}\n\n수집된 근거:\n{excerpt}"
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
    if score < LOW_CONFIDENCE_THRESHOLD:
        notes.append(
            "근거가 부족해 신뢰도가 낮습니다. 보고서 내용을 반드시 사람이 검토하세요."
        )

    await runtime.emit(
        run_id, "step_finished", step=STEP_NAME, confidence=score, reason=reason
    )
    return {
        "evidences": evidences,  # 필터링·마스킹된 근거로 교체
        "confidence": score,
        "verification": verification,
        "notes": notes,
    }
