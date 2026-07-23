"""
백필용: yt-dlp 로 채널 과거 영상을 열거한다(RSS 는 최근 ~15개만 제공하므로).
BACKFILL_SINCE(YYYY-MM-DD) 이후 영상 중 1차 키워드에 걸리는 후보를 반환.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from config import CHANNELS, CHANNEL_LOOKBACK
from fetch_rss import match_keywords


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
    for e in entries:
        if not e or not e.get("id"):
            continue
        videos.append({
            "video_id": e["id"],
            "title": e.get("title") or "",
            "description": "",
            "channel": channel["name"],
            "published": _entry_date(e),
            "link": f"https://www.youtube.com/watch?v={e['id']}",
        })
    print(f"  [hist] {channel['name']}: {len(videos)}개 열거")
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
