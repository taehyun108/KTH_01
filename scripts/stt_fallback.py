"""자막이 끝내 없는 영상의 음성을 호스팅 음성 인식으로 받아 적는다.

공급자(자동 선택 순서, STT_PROVIDER 로 고정 가능):
  groq        GROQ_API_KEY        — 무료 한도가 크다(시간당 오디오 약 2시간). whisper-large-v3
  nvidia      NVIDIA_API_KEY      — 이미 등록한 키. 호스팅 whisper-large-v3 → canary → parakeet 순
                                    (2026-11-13 시험: 한국어 유사도 98%·91%·89%). pip install nvidia-riva-client 필요
  elevenlabs  ELEVENLABS_API_KEY  — 무료 월 한도가 작다(약 1만 자)

집 PC 에서만 쓴다. Actions 러너는 유튜브 오디오 다운로드가 막혀 있다.
키는 환경변수로만 받는다(저장소·채팅에 적지 말 것).

비용·정확도를 지키려고 '자막이 없을 때만', '올라온 지 한참 지난 영상만' 쓴다.
유튜브 자동 자막은 방송 몇 시간 뒤에 붙는 경우가 많아, 먼저 기다렸다 받는 편이 공짜다.

긴 오디오는 ffmpeg 로 잘라 보낸다. Groq 무료는 파일당 25MB 라서
16kHz 모노 32kbps 로 줄인 뒤 CHUNK_SEC 단위로 나눈다(15분 ≈ 3.6MB).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

CHUNK_SEC = int(os.getenv("STT_CHUNK_SEC", "900"))
TIMEOUT_SEC = int(os.getenv("STT_TIMEOUT_SEC", "900"))
MAX_RETRY_429 = 4

# NVIDIA 호스팅 음성 인식: 이름으로 함수 ID 를 찾아(목록 API) 한국어로 보낸다.
NVIDIA_ASR_PREFERENCE = ("ai-whisper-large-v3", "ai-canary-1b-asr",
                         "ai-parakeet-1_1b-rnnt-multilingual-asr")
NVIDIA_CHUNK_SEC = 60        # 16kHz 모노 16비트 wav 60초 ≈ 1.9MB — gRPC 기본 4MB 한도 안
NVIDIA_CALL_TIMEOUT = 120    # 응답 없는 호출이 전체를 붙잡지 않게(2026-11-13 시험에서 모델 6개가 그랬다)
_nvidia_ids: dict[str, str] = {}

PROVIDERS = {
    "groq": {"env": "GROQ_API_KEY",
             "url": "https://api.groq.com/openai/v1/audio/transcriptions",
             "model": os.getenv("GROQ_STT_MODEL", "whisper-large-v3"),
             "lang": "ko", "source": "stt-groq"},
    "nvidia": {"env": "NVIDIA_API_KEY", "lang": "ko-KR", "source": "stt-nvidia"},
    "elevenlabs": {"env": "ELEVENLABS_API_KEY",
                   "url": "https://api.elevenlabs.io/v1/speech-to-text",
                   "model": os.getenv("STT_MODEL", "scribe_v1"),
                   "lang": "kor", "source": "stt-elevenlabs"},
}


def provider() -> str | None:
    """사용할 공급자. STT_PROVIDER 가 있으면 그것, 없으면 키가 있는 첫 번째(groq 우선)."""
    want = os.getenv("STT_PROVIDER", "").strip().lower()
    names = [want] if want in PROVIDERS else list(PROVIDERS)
    for n in names:
        if os.getenv(PROVIDERS[n]["env"], "").strip():
            return n
    return None


def available() -> bool:
    return provider() is not None


def source_label() -> str:
    p = provider()
    return PROVIDERS[p]["source"] if p else "stt"


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


def split_audio(path: Path, out_dir: Path, chunk_sec: int = CHUNK_SEC,
                fmt: str = "mp3") -> list[Path]:
    """16kHz 모노로 줄여 chunk_sec 단위로 자른다(mp3 32kbps 또는 wav 16비트). 순서대로 돌려준다."""
    pattern = out_dir / f"chunk_%03d.{fmt}"
    codec = ["-b:a", "32k"] if fmt == "mp3" else ["-sample_fmt", "s16"]
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-ac", "1",
           "-ar", "16000", *codec, "-f", "segment",
           "-segment_time", str(chunk_sec), "-reset_timestamps", "1", str(pattern)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {p.stderr.strip()[:120]}")
    parts = sorted(out_dir.glob(f"chunk_*.{fmt}"))
    if not parts:
        raise RuntimeError("오디오를 자르지 못했습니다")
    return parts


def _nvidia_function_ids(key: str) -> list[tuple[str, str]]:
    """선호 순서대로 (이름, 함수 ID). 목록 API 에서 ACTIVE 인 것만. NVIDIA_ASR_FUNCTION_ID 로 고정 가능."""
    import requests

    pinned = os.getenv("NVIDIA_ASR_FUNCTION_ID", "").strip()
    if pinned:
        return [("지정", pinned)]
    if not _nvidia_ids:
        r = requests.get("https://api.nvcf.nvidia.com/v2/nvcf/functions",
                         headers={"Authorization": f"Bearer {key}"}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"NVIDIA 함수 목록 HTTP {r.status_code}")
        for f in r.json().get("functions", []):
            if f.get("status") == "ACTIVE":
                _nvidia_ids[f.get("name", "")] = f["id"]
    found = [(n, _nvidia_ids[n]) for n in NVIDIA_ASR_PREFERENCE if n in _nvidia_ids]
    if not found:
        raise RuntimeError("NVIDIA 에서 쓸 수 있는 음성 인식 모델을 찾지 못했습니다")
    return found


def _nvidia_chunk(fid: str, key: str, wav: Path) -> str:
    """wav 한 조각을 Riva gRPC 로 받아 적는다. 응답이 없으면 NVIDIA_CALL_TIMEOUT 초 뒤 포기."""
    import concurrent.futures as cf

    def call() -> str:
        import riva.client
        auth = riva.client.Auth(use_ssl=True, uri="grpc.nvcf.nvidia.com:443",
                                metadata_args=[["function-id", fid],
                                               ["authorization", f"Bearer {key}"]])
        cfg = riva.client.RecognitionConfig(language_code=PROVIDERS["nvidia"]["lang"],
                                            max_alternatives=1, enable_automatic_punctuation=True)
        riva.client.add_audio_file_specs_to_config(cfg, str(wav))
        resp = riva.client.ASRService(auth).offline_recognize(wav.read_bytes(), cfg)
        return " ".join(r.alternatives[0].transcript for r in resp.results).strip()

    ex = cf.ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(call).result(timeout=NVIDIA_CALL_TIMEOUT)
    except cf.TimeoutError as exc:
        raise RuntimeError(f"NVIDIA 응답이 {NVIDIA_CALL_TIMEOUT}초 안에 오지 않았습니다") from exc
    except ImportError as exc:
        raise RuntimeError("pip install nvidia-riva-client 가 필요합니다") from exc
    finally:
        ex.shutdown(wait=False)


def _transcribe_nvidia(path: Path, key: str) -> str:
    """선호 모델 순서로 시도하고, 한 모델이 실패하면 다음 모델로 넘어간다(조각 전체를 같은 모델로)."""
    last = ""
    with tempfile.TemporaryDirectory() as tmp:
        parts = split_audio(path, Path(tmp), NVIDIA_CHUNK_SEC, fmt="wav")
        for name, fid in _nvidia_function_ids(key):
            try:
                texts = [_nvidia_chunk(fid, key, p) for p in parts]
                return " ".join(t for t in texts if t).strip()
            except RuntimeError as exc:
                last = f"{name}: {str(exc)[:100]}"
    raise RuntimeError(f"NVIDIA 음성 인식이 모두 실패했습니다 — {last}")


def _post(name: str, path: Path) -> str:
    import requests

    cfg = PROVIDERS[name]
    key = os.getenv(cfg["env"], "").strip()
    if not key:
        raise RuntimeError(f"{cfg['env']} 가 없습니다")
    headers = ({"xi-api-key": key} if name == "elevenlabs"
               else {"Authorization": f"Bearer {key}"})
    data = ({"model_id": cfg["model"], "language_code": cfg["lang"]} if name == "elevenlabs"
            else {"model": cfg["model"], "language": cfg["lang"],
                  "response_format": "json", "temperature": "0"})
    for attempt in range(MAX_RETRY_429 + 1):
        with open(path, "rb") as f:
            res = requests.post(cfg["url"], headers=headers, data=data,
                                files={"file": (path.name, f)}, timeout=TIMEOUT_SEC)
        if res.status_code == 429 and attempt < MAX_RETRY_429:
            # 시간당 오디오 한도에 닿았다 — 안내된 시간만큼 기다렸다 다시 보낸다.
            try:
                wait = float(res.headers.get("retry-after", ""))
            except ValueError:
                wait = 30.0 * (attempt + 1)
            time.sleep(min(wait, 3700))
            continue
        if res.status_code != 200:
            # 응답 본문에 키는 실리지 않는다(요청 헤더에만 있다).
            raise RuntimeError(f"HTTP {res.status_code} {res.text[:160].replace(chr(10), ' ')}")
        try:
            return (res.json().get("text") or "").strip()
        except ValueError as exc:
            raise RuntimeError("응답을 읽지 못했습니다") from exc
    raise RuntimeError("한도 대기를 여러 번 했지만 계속 429 입니다")


def transcribe_file(path: Path, chunk_sec: int = CHUNK_SEC) -> str:
    """오디오 파일 하나를 (필요하면 잘라서) 받아 적는다. 실패하면 RuntimeError."""
    name = provider()
    if name is None:
        raise RuntimeError("음성 인식 키(GROQ_API_KEY·NVIDIA_API_KEY·ELEVENLABS_API_KEY)가 없습니다")
    if name == "nvidia":
        return _transcribe_nvidia(path, os.getenv("NVIDIA_API_KEY", "").strip())
    with tempfile.TemporaryDirectory() as tmp:
        parts = split_audio(path, Path(tmp), chunk_sec)
        texts = [_post(name, p) for p in parts]
    return " ".join(t for t in texts if t).strip()


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
