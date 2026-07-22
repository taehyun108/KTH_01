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

import random
import sys
import time
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


# YouTube 가 datacenter IP / 기본 UA 요청을 간헐 차단(404/500/429)하므로
# 브라우저 헤더 + 재시도로 안정화한다.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
RSS_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko,en-US;q=0.9,en;q=0.8",
    # 서버 요청 시 동의(consent) 리다이렉트/소프트 404 회피용 쿠키
    "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+000; SOCS=CAISEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg",
}
RSS_MAX_TRIES = 6


def _fetch_rss_bytes(url: str) -> tuple[bytes | None, Any]:
    """비-200 응답이면 백오프하며 재시도. (content, last_status)"""
    import requests

    last = None
    for attempt in range(RSS_MAX_TRIES):
        try:
            r = requests.get(url, headers=RSS_HEADERS, timeout=20)
            last = r.status_code
            if r.status_code == 200 and r.content:
                return r.content, last
        except Exception as exc:  # noqa: BLE001
            last = f"err:{exc.__class__.__name__}"
        time.sleep(2.5 * (attempt + 1) + random.random() * 1.5)
    return None, last


def fetch_channel(channel: dict[str, str]) -> list[dict[str, Any]]:
    """단일 채널 RSS 를 파싱해 영상 엔트리 리스트 반환."""
    import feedparser  # 런타임 의존성

    cid = channel["channel_id"]
    if not cid or cid.startswith("TODO"):
        print(f"  [skip] {channel['name']}: channel_id 미설정", file=sys.stderr)
        return []

    content, status = _fetch_rss_bytes(RSS_URL.format(channel_id=cid))
    if content is None:
        print(f"  [rss] {channel['name']}: 실패 status={status} (재시도 {RSS_MAX_TRIES}회 소진)",
              file=sys.stderr)
        return []

    feed = feedparser.parse(content)
    print(f"  [rss] {channel['name']}: entries={len(feed.entries)} status={status}")
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
    for i, ch in enumerate(CHANNELS):
        if i:
            time.sleep(1.0 + random.random())  # 채널 간 간격 (throttle 회피)
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
