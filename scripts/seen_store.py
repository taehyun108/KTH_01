"""이미 판정이 끝난 영상을 기억한다 — 같은 영상을 매 실행 다시 판정하지 않기 위해.

왜 필요한가
  후보 풀은 최근 30일을 열거하므로, 한 번 '무관'으로 걸러진 영상도 30일 동안
  매 실행(하루 2회) 다시 후보로 올라온다. 그런데 '무관' 판정 결과는
  drafts/ 에만 쓰였고 그 디렉터리는 커밋 대상(site/) 밖이라 러너와 함께 사라졌다.
  결과적으로 매 실행이 같은 영상 수십 건을 다시 Gemini 에 물어보며 하루치 쿼터를
  거기서 다 써 버렸고, 정작 새로 올라온 영상은 손도 못 댔다.

  그래서 판정 결과를 site/data 에 남겨 커밋한다.

재시도 정책
  · 무관(irrelevant)  — 영상 내용에 대한 판단이므로 바뀔 일이 없다. 다시 보지 않는다.
  · 근거부족(no-context) — 지금은 자막·설명을 못 구했을 뿐, 나중에 열릴 수 있다.
    RETRY_AFTER_DAYS 가 지나면 한 번 더 시도한다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from config import DATA_DIR

SKIPPED_JSON = DATA_DIR / "skipped.json"

REASON_IRRELEVANT = "무관"
REASON_IRRELEVANT_WEAK = "무관(설명글만 보고 판단)"
REASON_NO_CONTEXT = "근거부족"

# 이 기간이 지나면 다시 본다.
RETRY_AFTER_DAYS = 7

# 영구 배제하지 않고 나중에 다시 볼 사유들.
#   · 근거부족 — 지금 자막을 못 구했을 뿐, 나중에 열릴 수 있다.
#   · 무관(설명글만) — 200자짜리 설명글만 보고 내린 '무관' 판정은 근거가 약하다.
#     자막이 열리면 같은 영상이 관련 있다고 판정될 수 있으므로 영구 배제하면 안 된다.
#     자막을 확보한 상태에서 내린 '무관' 만 영구로 본다.
RETRYABLE = (REASON_NO_CONTEXT, REASON_IRRELEVANT_WEAK)

# 근거가 충분하다고 보는 자막 출처 (이때의 '무관'은 영구)
STRONG_SOURCES = ("youtube-transcript-api", "yt-dlp-captions", "gemini-video", "local-cache")


def irrelevant_reason(evidence_source: str) -> str:
    """'무관' 판정을 영구로 남길지, 나중에 다시 볼지 정한다."""
    return (REASON_IRRELEVANT if evidence_source in STRONG_SOURCES
            else REASON_IRRELEVANT_WEAK)


def load() -> dict[str, dict[str, Any]]:
    if not SKIPPED_JSON.exists():
        return {}
    try:
        data = json.loads(SKIPPED_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("skipped", {}) if isinstance(data, dict) else {}


def save(store: dict[str, dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SKIPPED_JSON.write_text(
        json.dumps({"skipped": store}, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")


def record(store: dict[str, dict[str, Any]], video_id: str, reason: str,
           title: str = "") -> None:
    if not video_id:
        return
    store[video_id] = {"reason": reason, "date": date.today().isoformat(),
                       "title": (title or "")[:80]}


def _stale(entry: dict[str, Any]) -> bool:
    """근거부족 기록이 재시도할 만큼 오래됐는가."""
    try:
        when = datetime.fromisoformat(entry.get("date", "")).date()
    except ValueError:
        return True     # 날짜가 깨졌으면 다시 본다
    return date.today() - when >= timedelta(days=RETRY_AFTER_DAYS)


def blocked_ids(store: dict[str, dict[str, Any]]) -> set[str]:
    """이번 실행에서 건너뛸 영상 id."""
    out = set()
    for vid, e in store.items():
        if e.get("reason") in RETRYABLE and _stale(e):
            continue        # 재시도 시점이 됐다
        out.add(vid)
    return out


def summary(store: dict[str, dict[str, Any]]) -> str:
    n_irr = sum(1 for e in store.values() if e.get("reason") == REASON_IRRELEVANT)
    n_weak = sum(1 for e in store.values() if e.get("reason") == REASON_IRRELEVANT_WEAK)
    n_ctx = sum(1 for e in store.values() if e.get("reason") == REASON_NO_CONTEXT)
    retry = sum(1 for e in store.values()
                if e.get("reason") in RETRYABLE and _stale(e))
    return (f"판정 기록 {len(store)}건 "
            f"(무관 {n_irr} · 무관(약한근거) {n_weak} · 근거부족 {n_ctx}"
            + (f", 그중 {retry}건은 재시도 시점 도달" if retry else "") + ")")
