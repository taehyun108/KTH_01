"""유튜브 영상의 자막(또는 그에 준하는 근거)을 얻는 단 하나의 입구.

순서: 캐시 → youtube-transcript-api → yt-dlp 자막 → 영상 설명글 → (선택) 음성 인식.
호출하는 쪽은 acquire() 하나만 알면 된다. 출처가 무엇을 뜻하는지(WEAK_SOURCES),
연속 실패 상한, 로그 문구가 모두 여기에 모여 있다.

※ 예전에는 이 사다리가 generate_report·fetch_transcripts_local·check_transcripts 세 곳에
  복사돼 있었다. '자막 못 받음(unavailable)'의 의미가 파일마다 따로 놀다가 2026-11-12 에
  근거 없는 코스피 수치가 발행됐다.
"""
from __future__ import annotations

import json
import os
import re
import sys
from typing import Callable

import transcript_cache

# 근거가 약한 출처 — 자막 없이 제목·설명글만 본 경우.
WEAK_SOURCES = ("video-description", "unavailable")

def _parse_json3(raw: str) -> str:
    """유튜브 json3 자막 → 평문."""
    data = json.loads(raw)
    out = []
    for ev in data.get("events", []):
        for seg in ev.get("segs", []) or []:
            t = seg.get("utf8", "")
            if t and t != "\n":
                out.append(t)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _parse_vtt(raw: str) -> str:
    """WebVTT/SRT 자막 → 평문(타임스탬프·태그·중복 제거)."""
    lines, prev = [], None
    for ln in raw.splitlines():
        s = ln.strip()
        if (not s or s == "WEBVTT" or "-->" in s or s.isdigit()
                or s.startswith(("Kind:", "Language:", "NOTE"))):
            continue
        s = re.sub(r"<[^>]+>", "", s)          # <c>, <00:00:00.000> 등 제거
        s = re.sub(r"\s+", " ", s).strip()
        if s and s != prev:
            lines.append(s)
            prev = s
    return " ".join(lines).strip()


# GitHub Actions 의 데이터센터 IP 가 통째로 차단되면 yt-dlp 폴백은 영상마다
# 5개 클라이언트를 모두 시도하며 ~6초씩 태우고 전부 실패한다(후보 60건 → 약 6분 낭비).
# 연속 실패가 이 수치에 닿으면 이번 실행에서는 폴백을 포기한다(다음 실행에서 초기화).
YTDLP_FAIL_LIMIT = 8
_ytdlp_fails = 0

# youtube-transcript-api 도 같은 이유(러너 IP 차단)로 후보마다 똑같이 실패한다.
# 건당 1초 남짓이라 후보 100건이면 2분 가까이 그냥 버린다. 짝을 맞춰 상한을 둔다.
API_FAIL_LIMIT = 8
_api_fails = 0


def _ytdlp_transcript(video_id: str) -> tuple[str, str]:
    """youtube-transcript-api 실패 시 yt-dlp 로 (자동)자막→설명 순으로 확보."""
    global _ytdlp_fails

    if _ytdlp_fails >= YTDLP_FAIL_LIMIT:
        return "", "unavailable"
    try:
        import yt_dlp
        import requests
    except Exception:  # noqa: BLE001
        return "", "unavailable"

    url = f"https://www.youtube.com/watch?v={video_id}"
    class _Hush:  # yt-dlp 의 반복 ERROR 출력을 삼켜 로그 가독성을 지킨다(사유는 우리가 따로 기록)
        def debug(self, m): pass
        def info(self, m): pass
        def warning(self, m): pass
        def error(self, m): pass

    base = {
        "quiet": True, "no_warnings": True, "skip_download": True, "ignoreerrors": True,
        "writesubtitles": True, "writeautomaticsub": True, "subtitleslangs": ["ko", "en"],
        "logger": _Hush(),
    }
    # 데이터센터 IP(GitHub Actions)는 기본 web 클라이언트에서 "Sign in to confirm you're not a bot"
    # 차단을 받는다. 차단이 덜한 플레이어 클라이언트를 순차 시도한다.
    client_sets = [["android"], ["ios"], ["tv_embedded"], ["web_safari"], []]
    info: dict = {}
    for clients in client_sets:
        opts = dict(base)
        if clients:
            opts["extractor_args"] = {"youtube": {"player_client": clients}}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                got = ydl.extract_info(url, download=False)
        except Exception:  # noqa: BLE001
            continue
        if got:
            info = got
            break
    if not info:
        _ytdlp_fails += 1
        if _ytdlp_fails == YTDLP_FAIL_LIMIT:
            print(f"  [자막] yt-dlp 폴백 {YTDLP_FAIL_LIMIT}회 연속 실패 — "
                  "이 실행에서는 폴백을 중단합니다(러너 IP 차단으로 판단).", file=sys.stderr)
        return "", "unavailable"
    _ytdlp_fails = 0   # 한 번이라도 성공하면 차단이 아니므로 카운터 초기화

    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    def _pick(caption_map: dict) -> str:
        for lang in ("ko", "en", "ko-KR", "en-US", "a.ko", "a.en"):
            tracks = caption_map.get(lang)
            if not tracks:
                continue
            for ext in ("json3", "srv3", "vtt", "srv1"):
                tr = next((t for t in tracks if t.get("ext") == ext), None)
                if not tr or not tr.get("url"):
                    continue
                try:
                    raw = requests.get(tr["url"], headers=ua, timeout=20).text
                except Exception:  # noqa: BLE001
                    continue
                text = _parse_json3(raw) if ext in ("json3", "srv3") else _parse_vtt(raw)
                if len(text) > 40:
                    return text
        return ""

    # 수동 자막 우선, 없으면 자동 생성 자막
    text = _pick(info.get("subtitles") or {}) or _pick(info.get("automatic_captions") or {})
    if len(text) > 40:
        return text, "yt-dlp-captions"

    # 자막이 전혀 없으면 영상 설명을 대체 컨텍스트로 사용
    desc = (info.get("description") or "").strip()
    if len(desc) > 80:
        return desc, "video-description"
    return "", "unavailable"


def _transcript_api(video_id: str) -> str:
    """youtube-transcript-api 로 자막 확보. 1.x(fetch) 우선, 0.6.x(get_transcript) 호환.

    ※ 1.0 에서 정적 get_transcript 가 제거되어 예전 코드는 AttributeError 로 전부 실패했다.
      실패 사유는 반드시 로그로 남겨 조용히 묻히지 않게 한다.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    if hasattr(YouTubeTranscriptApi, "fetch"):          # 1.x 인스턴스 API
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["ko", "en"])
        rows = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
        return " ".join(r["text"] for r in rows).strip()

    chunks = YouTubeTranscriptApi.get_transcript(video_id, languages=["ko", "en"])  # 0.6.x
    return " ".join(c["text"] for c in chunks).strip()


def _network_blocked() -> bool:
    return (os.getenv("GITHUB_ACTIONS") == "true"
            and os.getenv("TRANSCRIPT_NETWORK", "0").strip() != "1")


def get_transcript(video_id: str, use_cache: bool = True) -> tuple[str, str]:
    """자막 텍스트와 소스 표기를 반환. (text, source)

    0) 집 PC 가 받아 둔 캐시 → 1) youtube-transcript-api → 2) yt-dlp 자막 →
    3) 영상 설명 순으로 시도. 각 단계의 실패 사유를 로그로 남긴다
    (원인 없는 '자막 부재'를 방지).

    캐시를 맨 앞에 두는 이유: Actions 러너 IP 는 유튜브에 차단돼 1·2 단계가
    사실상 항상 실패한다. 가정용 IP 로 미리 받아 둔 것이 있으면 그것이 최선이다.
    """
    global _api_fails
    cached = transcript_cache.get(video_id) if use_cache else None
    if cached:
        text, src = cached
        print(f"  [자막] {video_id}: 캐시 사용 ({len(text)}자, 출처 {src})")
        return text, src

    # GitHub Actions 러너에서는 유튜브가 IP 를 막아 아래 두 단계가 <항상> 실패한다
    # (실행 로그마다 RequestBlocked). 후보마다 몇 초씩 버리고 로그만 어지럽히므로 러너에서는 건너뛴다.
    # 막힘이 풀렸는지는 transcript-check.yml 이 따로 확인한다. 다시 켜려면 TRANSCRIPT_NETWORK=1.
    if _network_blocked():
        return "", "unavailable"

    # 러너 IP 가 차단되면 이 호출은 후보 수백 건에 대해 전부 같은 이유로 실패한다.
    # 건당 1초씩만 잡아도 2분 넘게 버리므로, 연속으로 막히면 이번 실행에서는 접는다.
    # (yt-dlp 폴백에 이미 같은 장치가 있고, 그것과 짝을 맞춘 것이다)
    if _api_fails < API_FAIL_LIMIT:
        try:
            text = _transcript_api(video_id)
            if len(text) > 40:
                _api_fails = 0        # 한 번이라도 되면 차단이 아니다
                return text, "youtube-transcript-api"
            print(f"  [자막] {video_id}: transcript-api 결과가 너무 짧음({len(text)}자)",
                  file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            # 라이브러리 예외 본문이 12줄이라 그대로 찍으면 로그가 파묻힌다 → 한 줄로 축약
            _api_fails += 1
            if _api_fails == API_FAIL_LIMIT:
                print(f"  [자막] transcript-api {API_FAIL_LIMIT}회 연속 실패 — "
                      "이 실행에서는 더 시도하지 않습니다(러너 IP 차단으로 판단).",
                      file=sys.stderr)
            else:
                brief = " ".join(str(exc).split())[:120]
                print(f"  [자막] {video_id}: transcript-api 실패 — "
                      f"{exc.__class__.__name__}: {brief}", file=sys.stderr)

    text, source = _ytdlp_transcript(video_id)
    if source == "unavailable":
        print(f"  [자막] {video_id}: yt-dlp 폴백도 실패 — 제목·설명 기반으로 작성", file=sys.stderr)
    return text, source



def acquire(video_id: str, *, use_cache: bool = True,
            stt: Callable[[str], str] | None = None,
            stt_source: str = "stt") -> tuple[str, str]:
    """(자막 텍스트, 출처). 못 얻으면 ("", "unavailable").

    use_cache=False : 캐시를 건너뛴다(캐시를 채우는 수집기용).
    stt             : 마지막 수단으로 부를 함수(video_id → 텍스트). 쓰지 않으려면 None.
                      건수·길이·대기 시간 같은 정책은 호출하는 쪽이 이 함수 안에 담는다.
    """
    text, source = get_transcript(video_id, use_cache=use_cache)
    if text or stt is None:
        return text, source
    try:
        got = (stt(video_id) or "").strip()
    except Exception as exc:  # noqa: BLE001
        brief = " ".join(str(exc).split())[:100]
        print(f"  [자막] {video_id}: 음성 인식 실패 — {brief}", file=sys.stderr)
        return "", "unavailable"
    if len(got) > transcript_cache.MIN_CHARS:
        return got, stt_source
    return "", "unavailable"


def reset_state() -> None:
    """연속 실패 카운터를 초기화한다(테스트·새 실행 시작용)."""
    global _api_fails, _ytdlp_fails
    _api_fails = _ytdlp_fails = 0
