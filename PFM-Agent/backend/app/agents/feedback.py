"""
피드백 루프 판단 로직 (Verifier → Retriever 재검색).

Verifier 가 매긴 신뢰도가 기준치에 못 미치면 그래프는 Generator 로 가지 않고
**Retriever 로 되돌아가** 다른 검색어로 근거를 다시 모은다.
이 모듈은 그 판단에 필요한 **순수 함수**만 모아 두어, 그래프나 MCP 서버 없이도
단독으로 테스트할 수 있게 한다.

무한 루프 방지 (3중 안전장치)
-----------------------------
1. **회차 상한** — `max_iterations` 를 넘으면 무조건 진행한다.
   (설정값 `AGENT_MAX_ITERATIONS`, 하드 상한 `MAX_AGENT_ITERATIONS`)
2. **검색어 중복 금지** — 이미 시도한 검색어(`tried_queries`)는 다시 쓰지 않는다.
3. **새 검색어가 없으면 재검색하지 않는다** — 같은 조건을 반복해도 결과가
   같으므로 되돌아갈 이유가 없다.

또한 그래프 쪽에서 `retry_reason` 을 Retriever 진입 시 반드시 비우므로,
라우터가 같은 분기를 무한히 선택하는 일이 구조적으로 불가능하다.
"""

from __future__ import annotations

import json
import re

from app.agents.state import Evidence

#: 재검색 1회에 시도할 대체 검색어 최대 개수
MAX_RETRY_QUERIES: int = 3

#: 검색어로 쓰기에 의미 없는 단어 (조사·지시어·형식어)
_STOPWORDS: frozenset[str] = frozenset(
    {
        "그리고", "또는", "관련", "대해", "대한", "위한", "위해", "통해",
        "내용", "자료", "정보", "부분", "경우", "다음", "아래", "위의",
        "최근", "현재", "우리", "저희", "회사", "사내", "그것", "이것",
        "해줘", "주세요", "부탁", "please",
    }
)

#: 요청문에서 제거할 지시 동사 (검색어에는 도움이 되지 않음)
_INSTRUCTION_PATTERN = re.compile(
    r"(조사|정리|분석|작성|생성|요약|검토|만들|보고서|알려|찾아|검색|추출)\S*"
)

#: 단어 끝에 붙는 한국어 조사 (교착어 특성상 검색어에서 떼어내야 한다)
_PARTICLE_PATTERN = re.compile(
    r"(?:으로써|으로서|에서의|에게서|이라는|라는|으로|에서|에게|부터|까지|"
    r"와의|과의|의|를|을|은|는|이|가|에|도|만|와|과|로)$"
)

#: 조사를 떼기 전 최소 길이 (짧은 단어는 조사처럼 보여도 어간일 수 있다)
_MIN_STRIP_LENGTH: int = 3

#: 검색어로 채택할 단어 최소 길이
_MIN_WORD_LENGTH: int = 2


def normalize_query(text: str) -> str:
    """
    검색어 비교용 정규화. (공백 축약 + 소문자)

    "  소듐이온배터리   정책 " 과 "소듐이온배터리 정책" 을 같은 것으로 본다.
    """
    return re.sub(r"\s+", " ", text.strip()).lower()


def strip_particle(word: str) -> str:
    """
    단어 끝의 한국어 조사를 떼어낸다.

    예) "정책동향을" → "정책동향", "배터리에서" → "배터리"

    짧은 단어는 조사처럼 보이는 글자가 어간일 수 있어 그대로 둔다.
    """
    if len(word) < _MIN_STRIP_LENGTH:
        return word
    stripped = _PARTICLE_PATTERN.sub("", word)
    # 조사를 떼고 나서 너무 짧아지면 원본을 유지한다.
    return stripped if len(stripped) >= _MIN_WORD_LENGTH else word


def extract_keywords(user_request: str) -> list[str]:
    """
    요청문에서 검색에 쓸 핵심 단어를 뽑아낸다.

    지시 동사("~조사해서", "~보고서로 만들어줘")와 조사를 제거하고,
    불용어를 걸러낸 뒤 등장 순서를 유지해 반환한다.

    예) "소듐이온배터리 최근 정책동향을 조사해서 보고서로 만들어줘"
        → ["소듐이온배터리", "정책동향"]
    """
    text = _INSTRUCTION_PATTERN.sub(" ", user_request)
    words: list[str] = []
    seen: set[str] = set()

    for raw in re.findall(r"[0-9A-Za-z가-힣]+", text):
        word = strip_particle(raw)
        if len(word) < _MIN_WORD_LENGTH:
            continue
        lowered = word.lower()
        if lowered in _STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        words.append(word)

    return words


def fallback_queries(user_request: str) -> list[str]:
    """
    LLM 없이 만드는 대체 검색어. (폐쇄망·LLM 장애 대비)

    전략은 **점진적 확대(broadening)** 다. 신뢰도가 낮은 원인은 대개
    검색어가 너무 좁아 결과가 적기 때문이므로, 범위를 넓혀 가며 시도한다.

    1) 핵심 단어 3개까지 조합  (예: "소듐이온배터리 정책동향")
    2) 가장 긴 단어 하나        (예: "소듐이온배터리")
    3) 첫 단어 하나            (가장 넓은 검색)
    """
    words = extract_keywords(user_request)
    if not words:
        return []

    candidates: list[str] = []
    if len(words) >= 2:
        candidates.append(" ".join(words[:3]))

    longest = max(words, key=len)
    candidates.append(longest)

    if words[0] != longest:
        candidates.append(words[0])

    return select_new_queries(candidates, [], limit=MAX_RETRY_QUERIES)


def parse_query_response(raw: str) -> list[str]:
    """
    LLM 이 제안한 검색어 목록을 파싱한다.

    JSON 배열을 기대하지만, 코드블록이나 목록 기호가 섞여 와도 복구한다.
    """
    text = raw.strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass

    # JSON 이 아니면 줄 단위로 분해하고 목록 기호·인용부호를 제거한다.
    queries: list[str] = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        cleaned = cleaned.strip("\"'`,")
        if cleaned:
            queries.append(cleaned)
    return queries


def select_new_queries(
    candidates: list[str], tried: list[str], *, limit: int = MAX_RETRY_QUERIES
) -> list[str]:
    """
    후보 검색어에서 **아직 시도하지 않은 것만** 골라낸다.

    Args:
        candidates: 제안된 검색어 후보
        tried: 이미 시도한 검색어
        limit: 최대 개수

    Returns:
        중복이 제거된 새 검색어 목록 (순서 유지)
    """
    used = {normalize_query(item) for item in tried}
    selected: list[str] = []

    for candidate in candidates:
        text = candidate.strip()
        key = normalize_query(text)
        if not key or key in used:
            continue
        used.add(key)
        selected.append(text)
        if len(selected) >= limit:
            break

    return selected


def should_retry(
    confidence: int, threshold: int, iteration: int, max_iterations: int
) -> bool:
    """
    재검색이 필요한지 판단한다.

    Args:
        confidence: Verifier 가 매긴 신뢰도 (0~100)
        threshold: 재검색 기준치 (이 점수 미만이면 재검색 대상)
        iteration: 현재 회차 (1 부터)
        max_iterations: 최대 회차 (1 이면 재검색하지 않음)

    Returns:
        되돌아가야 하면 True
    """
    if max_iterations <= 1:
        return False
    if iteration >= max_iterations:
        return False
    return confidence < threshold


def evidence_key(evidence: Evidence) -> tuple[str, str]:
    """
    근거 중복 판단용 키. (출처 + 본문 앞부분)

    재검색 시 같은 문서가 다시 걸려도 보고서에 두 번 들어가지 않게 한다.
    """
    source = evidence.get("source", "").strip()
    content = re.sub(r"\s+", " ", evidence.get("content", "")).strip()[:200]
    return (source, content)


def merge_evidences(
    existing: list[Evidence], fresh: list[Evidence]
) -> list[Evidence]:
    """
    기존 근거와 새로 찾은 근거를 합친다. (중복 제거, 기존 순서 우선)

    재검색은 **누적**이다. 이전 회차에서 찾은 근거를 버리면 재검색이
    오히려 결과를 나쁘게 만들 수 있다.
    """
    merged: list[Evidence] = []
    seen: set[tuple[str, str]] = set()

    for evidence in [*existing, *fresh]:
        key = evidence_key(evidence)
        if key in seen:
            continue
        seen.add(key)
        merged.append(evidence)

    return merged
