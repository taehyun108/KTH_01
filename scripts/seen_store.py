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
# 쇼츠 — 본편에서 잘라 낸 조각이라 같은 내용이 중복 발행된다. 영상의 성질이므로 영구.
# (2026-08-11: RSS 병합이 쇼츠를 되살려 한 건이 실제로 발행됐다)
REASON_SHORTS = "쇼츠"
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


def _fills(entry_date: str, prefer: set[str]) -> bool:
    """이 기록이 <빈 날>을 메울 가능성이 있는가.

    skipped.json 은 영상 게시일이 아니라 <판정한 날>을 적는다. 빈 날에 올라온
    영상은 그날이나 다음 날 판정되므로, 두 날을 모두 후보로 본다.
    """
    if not prefer or not entry_date:
        return False
    if entry_date in prefer:
        return True
    try:
        prev = (datetime.fromisoformat(entry_date).date()
                - timedelta(days=1)).isoformat()
    except ValueError:
        return False
    return prev in prefer


def thaw_oldest(store: dict[str, dict[str, Any]], blocked: set[str],
                limit: int, prefer_dates: set[str] | None = None) -> list[str]:
    """재시도 기한을 <기다리지 않고> 오래된 것부터 limit 건 풀어 준다.

    ※ 왜 필요한가 (2026-08-16)
      그날 발행이 0건이었다. 후보가 없어서가 아니었다. 재시도 대상 101건이
      전부 7일 타이머에 묶여 있었고(무관(약한근거) 49건은 08-21, 근거부족
      26건은 08-19 에야 풀린다), 그래서 그날 새로 올라온 영상 <단 1건>만
      후보가 됐다. 그 1건이 근거부족으로 끝나자 그날은 통째로 비었다.

      재시도 기한은 쿼터를 아끼려고 둔 것이지 발행을 멈추려고 둔 것이 아니다.
      오늘 아직 한 건도 못 냈다면, 아껴 둘 쿼터가 아니라 쓸 쿼터가 남은 것이다.

    순서
      1) 빈 날을 <실제로 메울 수 있는> 기록 (prefer_dates)
         리포트 날짜는 영상 게시일을 따르므로, 08-16 칸을 채우는 것은 그날 영상뿐이다.
      2) 그 외에는 오래된 것부터
         기록이 오래됐을수록 그때의 판단 근거(설명글 0자 등)가 지금과 다를
         가능성이 크다. 공식 API 로 설명글을 채우기 시작한 뒤로는 특히 그렇다.
    """
    if limit <= 0:
        return []
    prefer = prefer_dates or set()
    pool = [(0 if _fills(e.get("date", ""), prefer) else 1, e.get("date", ""), vid)
            for vid, e in store.items()
            if vid in blocked and e.get("reason") in RETRYABLE]
    pool.sort()
    return [vid for _, _, vid in pool[:limit]]


def summary(store: dict[str, dict[str, Any]]) -> str:
    n_irr = sum(1 for e in store.values() if e.get("reason") == REASON_IRRELEVANT)
    n_weak = sum(1 for e in store.values() if e.get("reason") == REASON_IRRELEVANT_WEAK)
    n_ctx = sum(1 for e in store.values() if e.get("reason") == REASON_NO_CONTEXT)
    retry = sum(1 for e in store.values()
                if e.get("reason") in RETRYABLE and _stale(e))
    return (f"판정 기록 {len(store)}건 "
            f"(무관 {n_irr} · 무관(약한근거) {n_weak} · 근거부족 {n_ctx}"
            + (f", 그중 {retry}건은 재시도 시점 도달" if retry else "") + ")")
