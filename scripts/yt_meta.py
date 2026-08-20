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

# 마지막 enrich 결과 한 줄 — 실행 끝 요약에 실어 보내기 위한 것.
# 이 정보가 로그 <앞부분>에만 있어서 "붙었는지 아닌지"를 확인하려면 매번 로그를
# 수백 줄 거슬러 올라가야 했다. 결론은 끝에서도 보여야 한다.
LAST = "미실행"


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
                "fields": ("items(id,snippet(title,description,publishedAt),"
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
                # '2026-08-16T09:12:33Z' → '2026-08-16'
                "published": (sn.get("publishedAt") or "")[:10],
                "duration": _iso8601_seconds(
                    (it.get("contentDetails") or {}).get("duration", "")),
            }
        _fails = 0
    return out


def announce() -> None:
    """이 경로를 쓰는지 <반드시 한 줄> 남긴다.

    ※ 왜 굳이 로그를 남기는가
      처음에는 키가 없으면 조용히 건너뛰게 만들었습니다. 그랬더니 시크릿 이름이
      'YOURUBE_API_KEY' 로 잘못 들어갔을 때 아무 표시도 없어서, 붙었는지 아닌지를
      며칠 동안 추측해야 했습니다(2026-08-12).
      꺼져 있다는 사실도 <보여야> 정보입니다. 조용한 실패가 가장 비쌉니다.
    """
    if api_key():
        print("  [yt-api] 사용합니다 (설명글·영상 길이 보강)")
    else:
        print("  [yt-api] YOUTUBE_API_KEY 가 없어 건너뜁니다 — "
              "설명글 없는 후보는 계속 '근거부족'으로 남습니다.\n"
              "           저장소 Settings → Secrets and variables → Actions 에서 "
              "이름이 정확히 'YOUTUBE_API_KEY' 인지 확인하세요.", file=sys.stderr)


def enrich(candidates: list[dict], min_chars: int) -> tuple[int, int]:
    """설명이 부족한 후보를 골라 채우고, 길이로 쇼츠를 걸러 낸다.

    반환: (설명을 채운 건수, 쇼츠로 걸러 낸 건수)
    ※ candidates 는 <제자리에서> 수정되고, 쇼츠는 목록에서 제거됩니다.
    """
    global LAST
    announce()
    if not available():
        LAST = "키 없음/사용 불가"
        return (0, 0)

    from fetch_history import SHORT_IDS, is_short

    # 설명글이 부족하거나 <게시일을 모르는> 후보를 채운다.
    #
    # ※ 게시일을 왜 여기서 채우는가 (2026-08-18)
    #   yt-dlp 채널 열거(extract_flat)는 upload_date 도 timestamp 도 주지 않는다.
    #   진단해 보니 슈카월드 120건 전부 게시일이 <빈 문자열>이었다.
    #   그 결과 두 가지가 조용히 망가져 있었다.
    #     · 리포트 날짜가 영상 게시일이 아니라 <실행한 날>로 찍힌다
    #     · 최근 N일 창(MAX_AGE_DAYS)이 사실상 동작하지 않는다
    #   공식 API 의 snippet.publishedAt 이 이 구멍을 정확히 메운다. 같은 호출에
    #   묻어 오므로 유닛이 더 들지 않는다.
    #
    # ※ 길이를 <모르는> 후보도 반드시 넣는다 (2026-08-20)
    #   예전에는 '설명글이 부족하거나 게시일을 모르는' 후보만 조회했다.
    #   그런데 쇼츠를 거르는 근거가 바로 <길이>다. RSS 후보는 설명글도 게시일도
    #   갖고 오지만 길이는 안 준다. 그래서 설명글이 넉넉한 RSS 쇼츠는
    #   조회 대상에서 빠졌고 → 길이를 영영 모르고 → 쇼츠 판정을 못 받았다.
    #   yt-dlp 열거가 잡아 주지도 못한다. 쇼츠는 /videos 탭이 아니라
    #   /shorts 탭에 있어서 SHORT_IDS 에 애초에 안 들어오기 때문이다.
    #   조회 비용은 50건당 1유닛이라 전부 넣어도 하루 한도의 0.5% 도 안 쓴다.
    #   아끼려다 쇼츠를 내보내는 것이 훨씬 비싸다.
    need = [c["video_id"] for c in candidates
            if len((c.get("description") or "").strip()) < min_chars
            or not (c.get("published") or "").strip()
            or c.get("duration") is None]
    if not need:
        return (0, 0)

    print(f"  [yt-api] 설명글이 부족한 후보 {len(need)}건을 공식 API 로 조회합니다 "
          f"(약 {(len(need) + BATCH - 1) // BATCH}유닛)")
    meta = fetch(need)
    if not meta:
        LAST = f"조회 실패 (대상 {len(need)}건)"
        return (0, 0)

    filled = 0
    dated = 0
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
        if m["published"] and not (c.get("published") or "").strip():
            c["published"] = m["published"]
            dated += 1
        # 길이를 남겨 둔다 — 영상 분석 예산을 <분> 단위로 재는 데 쓴다.
        if m["duration"] and not c.get("duration"):
            c["duration"] = m["duration"]

    for c in shorts:
        candidates.remove(c)

    LAST = (f"설명글 {filled}건 확보 · 게시일 {dated}건 확보 · "
            f"쇼츠 {len(shorts)}건 제외 (조회 {len(need)}건)")
    print(f"  [yt-api] {LAST}")
    return (filled, len(shorts))
