"""
백필용: yt-dlp 로 채널 과거 영상을 열거한다(RSS 는 최근 ~15개만 제공하므로).
BACKFILL_SINCE(YYYY-MM-DD) 이후 영상 중 1차 키워드에 걸리는 후보를 반환.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from config import CHANNELS, CHANNEL_LOOKBACK, SHORTS_MAX_SECONDS, SHORTS_MARKERS
from fetch_rss import match_keywords


# 길이를 보고 '쇼츠'로 판정해 제외한 영상 id.
#
# ※ 왜 따로 모아 두는가 (2026-08-11 쇼츠가 발행된 사고)
#   RSS 에는 영상 길이가 없어서 '#shorts' 표식이 없는 쇼츠를 못 거른다.
#   길이를 아는 것은 yt-dlp 열거(여기)뿐인데, run_pipeline 이 두 목록을 합칠 때
#   설명글을 살리려고 RSS 쪽으로 덮어쓴다. 그러면 여기서 애써 뺀 쇼츠가
#   RSS 를 타고 그대로 되살아난다. 표식 없는 쇼츠는 이 경로로 100% 통과했다.
#   그래서 '뺐다'는 사실 자체를 남겨 두고, 병합 뒤에 한 번 더 걷어 낸다.
SHORT_IDS: set[str] = set()


def short_ids() -> set[str]:
    """이번 실행에서 길이 기준으로 쇼츠라고 판정한 영상 id."""
    return SHORT_IDS


def is_short(duration: Any, title: str = "", description: str = "") -> bool:
    """쇼츠인지 판정. 길이를 알면 길이로, 모르면 제목·설명의 표식으로 본다."""
    try:
        if duration is not None and 0 < float(duration) <= SHORTS_MAX_SECONDS:
            return True
    except (TypeError, ValueError):
        pass
    blob = f"{title} {description}".lower()
    return any(m.lower() in blob for m in SHORTS_MARKERS)


def _entry_date(e: dict[str, Any]) -> str:
    ud = e.get("upload_date")
    if isinstance(ud, str) and len(ud) == 8 and ud.isdigit():
        return f"{ud[:4]}-{ud[4:6]}-{ud[6:]}"
    ts = e.get("timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(int(ts), timezone.utc).date().isoformat()
        except Exception:  # noqa: BLE001
            pass
    return ""


def fetch_channel_history(channel: dict[str, str], lookback: int) -> list[dict[str, Any]]:
    import yt_dlp  # 런타임 의존성

    cid = channel["channel_id"]
    if not cid or cid.startswith("TODO"):
        return []
    url = f"https://www.youtube.com/channel/{cid}/videos"
    opts = {
        "extract_flat": "in_playlist", "playlistend": lookback,
        "quiet": True, "no_warnings": True, "skip_download": True, "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  [yt-dlp] {channel['name']} 실패: {exc}", file=sys.stderr)
        return []

    entries = (info or {}).get("entries") or []
    videos = []
    n_shorts = 0
    for e in entries:
        if not e or not e.get("id"):
            continue
        # 쇼츠 제외 — 본편에서 잘라 낸 조각이라 같은 내용이 중복 생성된다.
        # 열거 결과에 duration 이 실려 오므로 길이로 먼저 거른다.
        if is_short(e.get("duration"), e.get("title", ""), e.get("description", "")):
            n_shorts += 1
            # RSS 가 같은 영상을 되살리지 못하도록 id 를 남긴다(위 SHORT_IDS 주석 참고)
            SHORT_IDS.add(e["id"])
            continue
        videos.append({
            "video_id": e["id"],
            # flat 열거에도 설명이 실려 오는 경우가 있다. 빈 문자열로 버리면
            # 근거(자막·설명) 게이트에 전부 걸려 신규 리포트가 0건이 된다.
            "description": (e.get("description") or "").strip(),
            "title": e.get("title") or "",
            "channel": channel["name"],
            "published": _entry_date(e),
            "link": f"https://www.youtube.com/watch?v={e['id']}",
        })
    n_desc = sum(1 for v in videos if v["description"])
    extra = f" · 쇼츠 제외 {n_shorts}개" if n_shorts else ""
    print(f"  [hist] {channel['name']}: {len(videos)}개 열거 (설명 있음 {n_desc}개){extra}")
    return videos


def collect_history(since: str) -> list[dict[str, Any]]:
    """since(YYYY-MM-DD) 이후 + 1차 키워드 통과 후보."""
    candidates = []
    for ch in CHANNELS:
        for v in fetch_channel_history(ch, CHANNEL_LOOKBACK):
            if since and v["published"] and v["published"] < since:
                continue  # 게시일이 확인되고 기준일보다 이르면 제외
            hits = match_keywords(f"{v['title']} {v['description']}")
            if hits:
                v["matched_keywords"] = hits
                candidates.append(v)
    return candidates
