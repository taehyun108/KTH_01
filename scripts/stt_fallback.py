"""자막이 끝내 없는 영상의 음성을 호스팅 음성 인식(ElevenLabs Scribe)으로 받아 적는다.

집 PC 에서만 쓴다. Actions 러너는 유튜브 오디오 다운로드가 막혀 있다.
키는 환경변수 ELEVENLABS_API_KEY 로만 받는다(저장소·채팅에 적지 말 것).

비용을 아끼고 정확도를 지키려고 '자막이 없을 때만', '올라온 지 한참 지난 영상만' 쓴다.
유튜브 자동 자막은 방송 몇 시간 뒤에 붙는 경우가 많아, 먼저 기다렸다 받는 편이 공짜다.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"
MODEL = os.getenv("STT_MODEL", "scribe_v1")
LANGUAGE = os.getenv("STT_LANGUAGE", "kor")
TIMEOUT_SEC = int(os.getenv("STT_TIMEOUT_SEC", "900"))
SOURCE = "stt-elevenlabs"


def available() -> bool:
    return bool(os.getenv("ELEVENLABS_API_KEY", "").strip())


def old_enough(published: str, min_hours: float, now: datetime | None = None) -> bool:
    """게시 후 min_hours 가 지났는가. 게시 시각을 모르면 True(막지 않는다)."""
    if not published:
        return True
    try:
        t = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return True
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - t).total_seconds() >= min_hours * 3600


def transcribe_file(path: Path) -> str:
    """오디오 파일 하나를 받아 적는다. 실패하면 RuntimeError."""
    import requests

    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY 가 없습니다")
    with open(path, "rb") as f:
        res = requests.post(
            ENDPOINT,
            headers={"xi-api-key": key},
            data={"model_id": MODEL, "language_code": LANGUAGE},
            files={"file": (path.name, f)},
            timeout=TIMEOUT_SEC,
        )
    if res.status_code != 200:
        # 응답 본문에 키는 실리지 않는다(요청 헤더에만 있다).
        raise RuntimeError(f"HTTP {res.status_code} {res.text[:160].replace(chr(10), ' ')}")
    try:
        return (res.json().get("text") or "").strip()
    except ValueError as exc:
        raise RuntimeError("응답을 읽지 못했습니다") from exc


def download_audio(video_id: str, out_dir: Path, max_minutes: int = 0) -> Path:
    """yt-dlp 로 오디오만 받는다. max_minutes>0 이고 그보다 길면 받지 않는다(비용 상한)."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "format": "bestaudio[ext=m4a]/bestaudio",
            "outtmpl": str(out_dir / "%(id)s.%(ext)s")}
    url = f"https://www.youtube.com/watch?v={video_id}"
    if max_minutes > 0:
        with yt_dlp.YoutubeDL({**opts, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        if (info.get("duration") or 0) > max_minutes * 60:
            raise RuntimeError(f"영상이 {max_minutes}분보다 깁니다(비용 상한)")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
    files = sorted(out_dir.glob(f"{video_id}.*"))
    if not files:
        raise RuntimeError("오디오를 받지 못했습니다")
    return files[0]


def transcribe_youtube(video_id: str, max_minutes: int = 90) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        audio = download_audio(video_id, Path(tmp), max_minutes)
        return transcribe_file(audio)
