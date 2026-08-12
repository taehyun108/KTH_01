"""YouTube Data API — 설명글과 영상 길이를 공식 경로로 가져옵니다.

왜 필요한가
  후보의 대부분(yt-dlp 로 열거한 170여 건)이 <설명글 0자>입니다.
  yt-dlp 채널 열거는 extract_flat 이라 설명을 아예 주지 않고,
  RSS 는 설명을 주지만 채널당 최신 15개뿐입니다.
  그래서 열거한 후보는 자막도 설명도 없어 전부 '근거부족'으로 끝났습니다.

  공식 API 는 이 문제를 정면으로 풉니다.
    · videos.list 한 번에 <영상 50개>를 묶어 조회할 수 있습니다
    · 비용은 호출당 1유닛, 하루 무료 한도가 10,000유닛입니다
      → 후보 200건이라도 4회 호출, 4유닛이면 끝납니다
    · 스크래핑이 아니라 공식 경로라 Actions IP 에서도 막히지 않습니다

  가져오는 것 두 가지
    · description — 근거(설명글) 게이트를 통과시켜 줍니다
    · duration    — 쇼츠 판정을 <길이 기준>으로 확실하게 합니다
                    (RSS 후보는 지금까지 '#shorts' 표식으로만 걸렀습니다)

  자막은 못 가져옵니다. captions.download 는 <영상 소유자>만 쓸 수 있어서,
  남의 영상 자막은 이 API 로 받을 수 없습니다. 자막은 여전히 집 PC 나
  Gemini 영상 분석이 맡습니다.

키가 없으면 아무 일도 하지 않습니다 — 지금까지와 똑같이 동작합니다.
"""
from __future__ import annotations

import os
import re
import sys

API_URL = "https://www.googleapis.com/youtube/v3/videos"
BATCH = 50          # videos.list 가 한 번에 받는 id 개수 상한
TIMEOUT_SEC = 30
# 연속으로 이만큼 실패하면 이번 실행에서는 포기합니다(키 오류·한도 소진 등).
FAIL_LIMIT = 3
_fails = 0


def api_key() -> str:
    return (os.getenv("YOUTUBE_API_KEY") or "").strip()


def available() -> bool:
    if _fails >= FAIL_LIMIT or not api_key():
        return False
    try:
        import requests  # noqa: F401
    except ImportError:
        return False
    return True


def _iso8601_seconds(text: str) -> int | None:
    """'PT1H2M3S' → 3723. 파싱 실패하면 None(=길이 모름)."""
    m = re.fullmatch(r"P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text or "")
    if not m:
        return None
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + s


def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def fetch(video_ids: list[str]) -> dict[str, dict]:
    """{video_id: {"description": str, "duration": int|None, "title": str}}.

    실패하면 빈 dict 를 돌려줍니다 — 호출자는 지금까지처럼 진행하면 됩니다.
    """
    global _fails
    if not available() or not video_ids:
        return {}

    import requests

    out: dict[str, dict] = {}
    for batch in _chunks(list(dict.fromkeys(video_ids)), BATCH):
        try:
            r = requests.get(API_URL, timeout=TIMEOUT_SEC, params={
                "part": "snippet,contentDetails",
                "id": ",".join(batch),
                "key": api_key(),
                "fields": ("items(id,snippet(title,description),"
                           "contentDetails(duration))"),
            })
        except Exception as exc:  # noqa: BLE001
            _fails += 1
            print(f"  [yt-api] 호출 실패 — {exc.__class__.__name__}", file=sys.stderr)
            break

        if r.status_code != 200:
            _fails += 1
            body = " ".join(r.text.split())[:180]
            if r.status_code == 403:
                # 한도 소진이거나 키가 YouTube Data API 를 못 쓰는 상태입니다.
                print(f"  [yt-api] HTTP 403 — 키 권한이나 일일 한도를 확인하세요. {body}",
                      file=sys.stderr)
            else:
                print(f"  [yt-api] HTTP {r.status_code} — {body}", file=sys.stderr)
            break

        for it in (r.json().get("items") or []):
            sn = it.get("snippet") or {}
            out[it.get("id", "")] = {
                "title": (sn.get("title") or "").strip(),
                "description": (sn.get("description") or "").strip(),
                "duration": _iso8601_seconds(
                    (it.get("contentDetails") or {}).get("duration", "")),
            }
        _fails = 0
    return out


def enrich(candidates: list[dict], min_chars: int) -> tuple[int, int]:
    """설명이 부족한 후보를 골라 채우고, 길이로 쇼츠를 걸러 낸다.

    반환: (설명을 채운 건수, 쇼츠로 걸러 낸 건수)
    ※ candidates 는 <제자리에서> 수정되고, 쇼츠는 목록에서 제거됩니다.
    """
    if not available():
        return (0, 0)

    from fetch_history import SHORT_IDS, is_short

    need = [c["video_id"] for c in candidates
            if len((c.get("description") or "").strip()) < min_chars]
    if not need:
        return (0, 0)

    print(f"  [yt-api] 설명글이 부족한 후보 {len(need)}건을 공식 API 로 조회합니다 "
          f"(약 {(len(need) + BATCH - 1) // BATCH}유닛)")
    meta = fetch(need)
    if not meta:
        return (0, 0)

    filled = 0
    shorts: list[dict] = []
    for c in candidates:
        m = meta.get(c["video_id"])
        if not m:
            continue
        # 길이를 알게 됐으니 쇼츠 판정을 다시 한다 — 이번엔 표식이 아니라 <길이>로.
        if is_short(m["duration"], c.get("title", ""), m["description"]):
            SHORT_IDS.add(c["video_id"])
            shorts.append(c)
            continue
        if len((c.get("description") or "").strip()) < len(m["description"]):
            c["description"] = m["description"]
            filled += 1

    for c in shorts:
        candidates.remove(c)

    print(f"  [yt-api] 설명글 {filled}건 확보 · 길이로 쇼츠 {len(shorts)}건 제외")
    return (filled, len(shorts))
