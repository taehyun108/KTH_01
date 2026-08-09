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
REASON_NO_CONTEXT = "근거부족"

# 근거부족은 영구 배제가 아니다. 자막이 열릴 수 있으니 이 기간이 지나면 다시 본다.
RETRY_AFTER_DAYS = 7


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
        if e.get("reason") == REASON_NO_CONTEXT and _stale(e):
            continue        # 재시도 시점이 됐다
        out.add(vid)
    return out


def summary(store: dict[str, dict[str, Any]]) -> str:
    n_irr = sum(1 for e in store.values() if e.get("reason") == REASON_IRRELEVANT)
    n_ctx = sum(1 for e in store.values() if e.get("reason") == REASON_NO_CONTEXT)
    retry = sum(1 for e in store.values()
                if e.get("reason") == REASON_NO_CONTEXT and _stale(e))
    return (f"판정 기록 {len(store)}건 (무관 {n_irr} · 근거부족 {n_ctx}"
            + (f", 그중 {retry}건은 재시도 시점 도달" if retry else "") + ")")
