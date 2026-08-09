"""집 PC 가 받아 둔 자막을 저장·조회하는 캐시.

왜 필요한가
  GitHub Actions 러너의 IP 는 유튜브가 차단해서 자막을 한 건도 못 가져온다
  (RequestBlocked). 반면 가정용 인터넷은 막히지 않는다. 그래서 자막을 받는 일만
  집 PC 가 맡고, 결과를 이 캐시에 넣어 저장소에 올린다. Actions 는 캐시를 먼저
  보고, 있으면 그대로 쓴다.

  자막을 받는 쪽과 요약하는 쪽을 분리했기 때문에
  · PC 에는 Gemini API 키가 필요 없다(키는 계속 Actions 시크릿에만 둔다)
  · PC 가 꺼져 있어도 파이프라인은 지금과 똑같이 동작한다(캐시가 없을 뿐)

왜 site/ 밖인가
  site/ 아래 두면 GitHub Pages 로 그대로 공개 배포된다. 남의 영상 자막 전문을
  웹에 올리는 셈이고 배포 용량도 커진다. 저장소에는 두되 배포에서는 뺀다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from config import ROOT

CACHE_DIR = ROOT / "cache" / "transcripts"

# 후보 풀이 최근 30일이므로 그보다 넉넉히 지난 자막은 다시 쓸 일이 없다.
KEEP_DAYS = 45
# 이보다 짧으면 자막을 제대로 받은 것으로 보지 않는다(get_transcript 기준과 맞춤).
MIN_CHARS = 40


def _path(video_id: str) -> Path:
    return CACHE_DIR / f"{video_id}.json"


def get(video_id: str) -> tuple[str, str] | None:
    """(자막, 소스) 또는 없으면 None."""
    p = _path(video_id)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    text = (d.get("text") or "").strip()
    if len(text) < MIN_CHARS:
        return None
    return text, d.get("source") or "local-cache"


def put(video_id: str, text: str, source: str, title: str = "") -> bool:
    """자막을 캐시에 넣는다. 너무 짧으면 넣지 않는다."""
    text = (text or "").strip()
    if len(text) < MIN_CHARS:
        return False
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _path(video_id).write_text(json.dumps({
        "video_id": video_id,
        "title": (title or "")[:120],
        "source": source,
        "fetched": date.today().isoformat(),
        "chars": len(text),
        "text": text,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def has(video_id: str) -> bool:
    return get(video_id) is not None


def prune(keep_days: int = KEEP_DAYS) -> int:
    """오래된 캐시를 지운다. 저장소가 무한히 커지지 않게."""
    if not CACHE_DIR.exists():
        return 0
    cutoff = date.today() - timedelta(days=keep_days)
    n = 0
    for p in CACHE_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            when = datetime.fromisoformat(d.get("fetched", "")).date()
        except (json.JSONDecodeError, OSError, ValueError):
            p.unlink(missing_ok=True)   # 읽을 수 없는 파일은 정리
            n += 1
            continue
        if when < cutoff:
            p.unlink(missing_ok=True)
            n += 1
    return n


def stats() -> tuple[int, int]:
    """(파일 수, 총 글자 수)."""
    if not CACHE_DIR.exists():
        return 0, 0
    n = chars = 0
    for p in CACHE_DIR.glob("*.json"):
        try:
            chars += int(json.loads(p.read_text(encoding="utf-8")).get("chars", 0))
            n += 1
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    return n, chars
