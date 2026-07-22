"""
1단계: YouTube RSS 수집 + 1차 키워드 필터링(A/B/C).

동작:
  1. config.CHANNELS 의 각 채널 videos.xml(RSS) fetch
  2. 신규 영상 목록 확보 (published 최근순)
  3. 제목/설명에 A/B/C 키워드가 하나라도 걸리면 후보로 픽업

출력: 후보 영상 리스트(dict) — video_id, title, channel, published, matched_keywords

주의: 이 파일은 뼈대(skeleton)입니다. feedparser 미설치 환경에서도 import 가능하도록
      런타임 의존성은 함수 내부에서 로드합니다.
"""
from __future__ import annotations

import sys
from typing import Any

from config import CHANNELS, RSS_URL, ALL_KEYWORDS


def match_keywords(text: str) -> list[str]:
    """제목+설명에서 걸린 키워드 목록 반환 (1차 필터)."""
    text_l = (text or "").lower()
    hits = []
    for kw in ALL_KEYWORDS:
        if kw.lower() in text_l:
            hits.append(kw)
    return hits


def fetch_channel(channel: dict[str, str]) -> list[dict[str, Any]]:
    """단일 채널 RSS 를 파싱해 영상 엔트리 리스트 반환."""
    import feedparser  # 런타임 의존성

    cid = channel["channel_id"]
    if not cid or cid.startswith("TODO"):
        print(f"  [skip] {channel['name']}: channel_id 미설정", file=sys.stderr)
        return []

    feed = feedparser.parse(RSS_URL.format(channel_id=cid))
    videos = []
    for e in feed.entries:
        videos.append({
            "video_id": e.get("yt_videoid") or e.get("id", "").split(":")[-1],
            "title": e.get("title", ""),
            "description": (e.get("summary") or ""),
            "channel": channel["name"],
            "published": e.get("published", ""),
            "link": e.get("link", ""),
        })
    return videos


def collect_candidates() -> list[dict[str, Any]]:
    """모든 채널을 돌며 1차 키워드 필터를 통과한 후보를 모은다."""
    candidates = []
    for ch in CHANNELS:
        try:
            for v in fetch_channel(ch):
                hits = match_keywords(v["title"] + " " + v["description"])
                if hits:
                    v["matched_keywords"] = hits
                    candidates.append(v)
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] {ch['name']}: {exc}", file=sys.stderr)
    return candidates


if __name__ == "__main__":
    found = collect_candidates()
    print(f"1차 키워드 필터 통과 후보: {len(found)}건")
    for v in found:
        print(f"  - [{v['channel']}] {v['title']}  ← {v['matched_keywords'][:3]}")
