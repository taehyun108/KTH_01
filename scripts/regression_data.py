"""회귀 검사 — 자막·음성 인식·리포트 아카이브·환각 수치 방어.

실행은 test_keywords.py 가 이 파일의 check_* 함수를 자동으로 모아 돌린다(수동 목록 없음).
"""
from __future__ import annotations

import sys


# archive.yml 과 summarize-url.yml 은 <같은> KTH_01_GEMINI_API_KEY 하루 한도를
# 나눠 쓴다. archive.yml 이 하루 4회로 먼저 돌며 한도를 다 쓰면, 그 뒤에
# 즐겨찾기 탭에서 URL 을 제출한 사람은 예비 경로 하나 없이 바로 실패한다
# — 한쪽만 예비 경로(추가 키·GitHub Models·OpenAI)를 갖고 있으면 이 일이
# 조용히 반복된다(2026-10-28 발견). 두 워크플로가 같은 것을 받는지 고정한다.
def check_transcripts_module() -> list[str]:
    """자막 확보 사다리의 단일 입구 — 순서·캐시 우회·약한 출처·음성 인식 호출 조건."""
    import transcripts as tr
    out = []
    orig = (tr._transcript_api, tr._ytdlp_transcript, tr.transcript_cache.get)
    long = "가" * 100
    import os
    os.environ.pop("GITHUB_ACTIONS", None)      # 러너에서도 '집 PC' 경로의 동작을 검사한다(끝나면 harness 가 되돌린다)
    try:
        tr.reset_state()
        order = []
        tr.transcript_cache.get = lambda v: (long, "local-cache") if v == "hit" else None
        def api(v):
            order.append("api")
            if v in ("fail", "none"): raise RuntimeError("blocked")
            return long
        def ytdlp(v):
            order.append("yt")
            return ("", "unavailable") if v == "none" else (long, "yt-dlp-captions")
        tr._transcript_api, tr._ytdlp_transcript = api, ytdlp

        if tr.acquire("hit") != (long, "local-cache") or order:
            out.append("  [캐시 적중] 캐시를 쓰고 네트워크는 건드리지 않아야 합니다")
        order.clear()
        if tr.acquire("hit", use_cache=False)[1] != "youtube-transcript-api":
            out.append("  [use_cache=False] 캐시를 건너뛰고 API 로 가야 합니다")
        order.clear()
        if tr.acquire("fail")[1] != "yt-dlp-captions" or order != ["api", "yt"]:
            out.append(f"  [API 실패] yt-dlp 로 넘어가야 하는데 {order}")
        calls = []
        r = tr.acquire("none", stt=lambda v: calls.append(v) or long, stt_source="stt-x")
        if r != (long, "stt-x") or calls != ["none"]:
            out.append(f"  [자막 없음 + stt] 음성 인식 결과를 써야 하는데 {r[1]}")
        calls.clear()
        tr.acquire("fail", stt=lambda v: calls.append(v) or long)
        if calls:
            out.append("  [자막 있음] 음성 인식을 부르면 안 됩니다(비용)")
        def boom(v): raise RuntimeError("quota")
        if tr.acquire("none", stt=boom) != ("", "unavailable"):
            out.append("  [stt 예외] ('', 'unavailable') 이어야 합니다")
        if tr.acquire("none", stt=lambda v: "짧음") != ("", "unavailable"):
            out.append("  [stt 결과가 너무 짧음] 근거로 쓰면 안 됩니다")
        order.clear()
        os.environ["GITHUB_ACTIONS"] = "true"
        if tr.acquire("fail") != ("", "unavailable") or order:
            out.append(f"  [Actions 러너] 항상 막히는 자막 네트워크 시도를 건너뛰어야 하는데 {order}")
        if tr.acquire("hit")[1] != "local-cache":
            out.append("  [Actions 러너] 캐시는 그대로 써야 합니다")
        os.environ["TRANSCRIPT_NETWORK"] = "1"
        if tr.acquire("fail")[1] != "yt-dlp-captions":
            out.append("  [TRANSCRIPT_NETWORK=1] 다시 켤 수 있어야 합니다")
        os.environ.pop("GITHUB_ACTIONS"); os.environ.pop("TRANSCRIPT_NETWORK")
        if "unavailable" not in tr.WEAK_SOURCES or "yt-dlp-captions" in tr.WEAK_SOURCES:
            out.append("  [WEAK_SOURCES] unavailable 만 약한 출처여야 합니다")
        import generate_report as g
        if g.WEAK_SOURCES is not tr.WEAK_SOURCES:
            out.append("  [generate_report] WEAK_SOURCES 가 단일 정의가 아닙니다")
    finally:
        tr._transcript_api, tr._ytdlp_transcript, tr.transcript_cache.get = orig
        tr.reset_state()
    return out


def check_stt_fallback() -> list[str]:
    """자막 없는 영상의 음성 인식 폴백(Groq·NVIDIA) — 키 노출·분할·한도 대기·비용 상한."""
    import os, shutil, subprocess, tempfile
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    import stt_fallback as st
    import requests
    out = []
    keys = ("GROQ_API_KEY", "STT_PROVIDER", "NVIDIA_API_KEY", "NVIDIA_ASR_FUNCTION_ID")
    saved = {k: os.environ.pop(k, None) for k in keys}
    orig_post, orig_sleep, orig_split = requests.post, st.time.sleep, st.split_audio
    # ※ GitHub 러너에는 ffmpeg 이 없다. 2026-11-13 에 이 검사가 ffmpeg 을 직접 불러 러너에서 죽었고,
    #   그 바람에 뒤의 파이프라인 단계가 통째로 건너뛰어졌다. ffmpeg 이 없으면 분할만 흉내 낸다
    #   (음성 인식은 집 PC 전용 기능이라 러너에서 진짜 분할을 확인할 이유가 없다).
    has_ffmpeg = shutil.which("ffmpeg") is not None

    def make_audio(path):
        if has_ffmpeg:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=20", str(path)], check=True)
        else:
            path.write_bytes(b"x")

    def fake_split(path, out_dir, chunk_sec=900, fmt="mp3"):
        parts = []
        for i in range(-(-20 // chunk_sec)):        # 20초짜리 가짜 음성
            f = out_dir / f"chunk_{i:03d}.{fmt}"
            f.write_bytes(b"x")
            parts.append(f)
        return parts

    try:
        if not has_ffmpeg:
            st.split_audio = fake_split
        if st.available():
            out.append("  [키 없음] available() 이 True 입니다")
        os.environ["NVIDIA_API_KEY"] = "nv-key-0"
        os.environ["GROQ_API_KEY"] = "gq-key-1"
        if st.provider() != "groq":
            out.append("  [키 둘 다] 무료 한도가 큰 groq 가 우선이어야 합니다")
        os.environ["STT_PROVIDER"] = "nvidia"
        if st.provider() != "nvidia":
            out.append("  [STT_PROVIDER] 지정한 공급자가 선택되지 않았습니다")
        os.environ.pop("STT_PROVIDER")
        os.environ.pop("NVIDIA_API_KEY")

        class R:
            def __init__(s, code, body, headers=None):
                s.status_code, s._b, s.text, s.headers = code, body, str(body), headers or {}
            def json(s): return s._b
        calls = []
        def ok(url, **kw):
            calls.append((url, kw)); return R(200, {"text": f" 조각{len(calls)} "})
        requests.post = ok

        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "a.wav"
            make_audio(wav)
            text = st.transcribe_file(wav, chunk_sec=8)
        if len(calls) != 3:
            out.append(f"  [20초를 8초 단위로] 3조각이어야 하는데 {len(calls)}번 요청했습니다")
        if text != "조각1 조각2 조각3":
            out.append(f"  [조각 이어붙이기] 순서·공백이 잘못됐습니다: {text!r}")
        url, kw = calls[0]
        if "groq.com" not in url or kw["headers"].get("Authorization") != "Bearer gq-key-1":
            out.append("  [Groq] 주소 또는 Authorization 헤더가 잘못됐습니다")
        if kw["data"].get("language") != "ko" or kw["data"].get("model") != "whisper-large-v3":
            out.append("  [Groq] 언어(ko)·모델이 잘못됐습니다")

        seq = iter([R(429, "slow", {"retry-after": "7"}), R(200, {"text": "다시 성공"})])
        waits = []
        requests.post = lambda url, **kw: next(seq)
        st.time.sleep = lambda s: waits.append(s)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "c.mp3"; f.write_bytes(b"x")
            if st._post("groq", f) != "다시 성공":
                out.append("  [429 뒤 재시도] 결과를 받지 못했습니다")
        if waits != [7.0]:
            out.append(f"  [429 대기] retry-after 7초를 따라야 하는데 {waits}")

        # NVIDIA 공급자: 선택 순서·모델 우선순위·모델 실패 시 다음 모델·wav 분할
        os.environ.pop("GROQ_API_KEY")
        os.environ["NVIDIA_API_KEY"] = "nv-key-1"
        if st.provider() != "nvidia":
            out.append("  [NVIDIA 키만] provider() 가 nvidia 가 아닙니다")
        os.environ["GROQ_API_KEY"] = "gq-key-1"
        if st.provider() != "groq":
            out.append("  [Groq+NVIDIA] groq 가 먼저여야 합니다")
        os.environ.pop("GROQ_API_KEY")
        fl = {"functions": [
            {"name": "ai-parakeet-1_1b-rnnt-multilingual-asr", "id": "id-parakeet", "status": "ACTIVE"},
            {"name": "ai-canary-1b-asr", "id": "id-canary", "status": "ACTIVE"},
            {"name": "ai-whisper-large-v3", "id": "id-whisper", "status": "ACTIVE"},
            {"name": "ai-parakeet-ctc-0_6b-es", "id": "id-es", "status": "ACTIVE"}]}
        had_get = hasattr(requests, "get")
        orig_get = getattr(requests, "get", None)
        requests.get = lambda url, **kw: R(200, fl)
        st._nvidia_ids.clear()
        ids = [n for n, _ in st._nvidia_function_ids("nv-key-1")]
        if ids != ["ai-whisper-large-v3", "ai-canary-1b-asr", "ai-parakeet-1_1b-rnnt-multilingual-asr"]:
            out.append(f"  [NVIDIA 모델 우선순위] whisper→canary→parakeet 여야 하는데 {ids}")
        fl["functions"][2]["status"] = "INACTIVE"
        st._nvidia_ids.clear()
        if "ai-whisper-large-v3" in [n for n, _ in st._nvidia_function_ids("nv-key-1")]:
            out.append("  [비활성 모델] INACTIVE 인 whisper 가 후보에 들어갔습니다")
        fl["functions"][2]["status"] = "ACTIVE"
        st._nvidia_ids.clear()
        if had_get:
            requests.get = orig_get
        else:
            del requests.get
        tried = []
        orig_chunk = st._nvidia_chunk
        def fake_chunk(fid, key, wav):
            tried.append(fid)
            if fid == "id-whisper":
                raise RuntimeError("Unavailable model")
            return "안녕"
        st._nvidia_chunk = fake_chunk
        st._nvidia_ids.update({"ai-whisper-large-v3": "id-whisper", "ai-canary-1b-asr": "id-canary"})
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "a.wav"
            make_audio(wav)
            parts = st.split_audio(wav, Path(d), 8, fmt="wav")
            if len(parts) != 3 or parts[0].suffix != ".wav":
                out.append(f"  [wav 분할] 20초/8초 → 3조각 wav 여야 하는데 {len(parts)}조각")
            res = st._transcribe_nvidia(wav, "nv-key-1")
        st._nvidia_chunk = orig_chunk
        st._nvidia_ids.clear()
        if "id-canary" not in tried or tried[0] != "id-whisper":
            out.append(f"  [모델 실패 시 다음 모델] whisper 실패 뒤 canary 로 넘어가야 하는데 {tried}")

        requests.post = lambda url, **kw: R(401, {"detail": "bad"})
        try:
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / "c.mp3"; f.write_bytes(b"x")
                st._post("groq", f)
            out.append("  [HTTP 401] 예외가 나지 않았습니다")
        except RuntimeError as exc:
            if "gq-key-1" in str(exc):
                out.append("  [오류 메시지] API 키가 메시지에 노출됩니다")
    finally:
        requests.post, st.time.sleep, st.split_audio = orig_post, orig_sleep, orig_split
        for k, v in saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    if st.old_enough((now - timedelta(hours=2)).isoformat(), 12, now):
        out.append("  [2시간 전 영상] 기다려야 하는데 통과했습니다")
    if not st.old_enough((now - timedelta(hours=30)).isoformat(), 12, now):
        out.append("  [30시간 전 영상] 통과해야 하는데 막혔습니다")
    if not st.old_enough("", 12, now):
        out.append("  [게시 시각 모름] 막으면 안 됩니다")
    src = (Path(__file__).resolve().parent / "fetch_transcripts_local.py").read_text(encoding="utf-8")
    if "stt_fallback.old_enough" not in src or "stt_used < args.stt_limit" not in src:
        out.append("  [fetch_transcripts_local] 대기 시간·건수 상한 배선이 없습니다")
    return out


def check_report_archive() -> list[str]:
    """reports.json 단일 입구 — 병합·삭제·원자적 기록·분류 보정."""
    import json, tempfile
    from pathlib import Path
    import report_archive as ra
    out = []
    saved = (ra.REPORTS_JSON, ra.DATA_DIR, ra.NEWS_DIR, ra.MAX_REPORTS)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        ra.DATA_DIR, ra.NEWS_DIR = d / "data", d / "news"
        ra.REPORTS_JSON = ra.DATA_DIR / "reports.json"
        ra.NEWS_DIR.mkdir(parents=True)
        ra.MAX_REPORTS = None
        try:
            def rep(i, date, vid, cat="macro"):
                (ra.NEWS_DIR / f"{i}.html").write_text("x", encoding="utf-8")
                return {"id": i, "date": date, "url": f"{i}.html", "video_id": vid,
                        "category": cat, "relation": "direct", "title": i}
            ra.merge([rep("a", "2026-01-01", "va"), rep("b", "2026-01-03", "vb", cat="없는분류")])
            ra.merge([rep("a", "2026-01-01", "va")])          # 같은 id 는 갱신(중복 안 생김)
            got = ra.load()
            if [r["id"] for r in got] != ["b", "a"]:
                out.append(f"  [병합] 중복 없이 최신순이어야 하는데 {[r['id'] for r in got]}")
            if got[0]["category"] == "없는분류":
                out.append("  [분류 보정] 등록 안 된 카테고리가 그대로 남았습니다")
            raw = ra.REPORTS_JSON.read_text(encoding="utf-8")
            if '"generated_at"' not in raw or '"channels"' not in raw or raw.startswith('{"'):
                out.append("  [기록 형식] generated_at·channels·들여쓰기가 있어야 합니다")
            if list(ra.DATA_DIR.glob("*.tmp")):
                out.append("  [원자적 기록] 임시 파일이 남았습니다")
            gone = ra.remove_ids(["a"])
            if [r["id"] for r in gone] != ["a"] or (ra.NEWS_DIR / "a.html").exists():
                out.append("  [삭제] 인덱스와 HTML 이 함께 지워져야 합니다")
            if [r["id"] for r in ra.load()] != ["b"]:
                out.append("  [삭제 뒤 인덱스] b 만 남아야 합니다")
            if ra.remove_ids(["없음"]) != []:
                out.append("  [없는 id] 빈 목록이어야 합니다")
            gone = ra.remove_video_ids(["vb"])
            if len(gone) != 1 or ra.load() != []:
                out.append("  [video_id 로 삭제] 지워지지 않았습니다")
            ra.MAX_REPORTS = 1
            ra.merge([rep("c", "2026-02-01", "vc"), rep("d", "2026-02-02", "vd")])
            if [r["id"] for r in ra.load()] != ["d"] or (ra.NEWS_DIR / "c.html").exists():
                out.append("  [보관 상한] 초과분의 인덱스와 HTML 이 정리돼야 합니다")
        finally:
            ra.REPORTS_JSON, ra.DATA_DIR, ra.NEWS_DIR, ra.MAX_REPORTS = saved
    import build_index, delete_report, check_published, inspect
    if build_index.load_existing is not ra.load or build_index.merge is not ra.merge:
        out.append("  [build_index] 기존 이름이 report_archive 를 가리켜야 합니다")
    for mod in (delete_report, check_published):
        if "REPORTS_JSON.write_text" in inspect.getsource(mod):
            out.append(f"  [{mod.__name__}] reports.json 을 직접 쓰고 있습니다 — report_archive 를 쓰세요")
    return out


def check_hallucination_guards() -> list[str]:
    """2026-11-12: 자막 없이 입력에 없던 '코스피 2,500선'이 발행됐다."""
    import generate_report as g
    out = []
    meta = {"title": "코스피 흔들리는 이유", "description": ""}
    bad = {"title": "코스피 2,500선 위태", "meta_description": "코스피가 2,500선 아래로",
           "_transcript_source": "unavailable", "relation": "indirect"}

    def raises(data, tr="", ref=None, force=False):
        try:
            g.verify_grounding(data, meta, tr, reference=ref, force=force)
        except g.InsufficientContext:
            return True
        return False

    if not raises(bad):
        out.append("  [자막 없음 + 입력에 없는 '2,500선'] 기각되지 않았습니다")
    if raises(bad, tr="오늘 코스피는 2,500선에서 마감했다"):
        out.append("  [입력에 실제로 있는 수치] 잘못 기각됐습니다")
    if raises(dict(bad, _transcript_source="youtube-transcript-api")):
        out.append("  [정식 자막 출처] 약한 출처 규칙이 잘못 적용됐습니다")
    if not raises(dict(bad, title="반도체 약세", meta_description="약세", relation="context")):
        out.append("  [자막 없음 + context] 기각되지 않았습니다")
    ref = [{"title": f"코스피 {v}선 돌파", "summary": ""} for v in (6000, 6400, 7000)]
    gem = dict(bad, _transcript_source="gemini-video")
    if not raises(gem, ref=ref):
        out.append("  [코스피 2,500 vs 최근 중앙값 6,400] 기각되지 않았습니다")
    if raises(dict(gem, title="코스피 5,300선 하회", meta_description="5,300"), ref=ref):
        out.append("  [코스피 5,300 (중앙값 -17%)] 잘못 기각됐습니다")
    src = open(g.__file__, encoding="utf-8").read()
    if 'transcript_source in WEAK_SOURCES' not in src:
        out.append("  [source_note] unavailable 이 약한 출처로 취급되지 않습니다")
    return out


def check_transcript_trim_limit() -> list[str]:
    """자막 상한 — 통상 방송(약 2.7만 자)은 통째로 들어가고, 더 길면 앞·뒤를 남긴다."""
    import generate_report as g
    out = []
    if g.MAX_TRANSCRIPT_CHARS != 30000:
        out.append(f"  [자막 상한] 기본값이 30,000자여야 하는데 {g.MAX_TRANSCRIPT_CHARS:,}자입니다")
    whole = "가" * 27000
    if g.trim_transcript(whole) != whole:
        out.append("  [2.7만 자 방송] 잘리면 안 됩니다(가운데 내용이 사라집니다)")
    long = "A" * 20000 + "B" * 20000 + "C" * 20000
    got = g.trim_transcript(long)
    if "생략" not in got or not got.startswith("A") or not got.rstrip().endswith("C") or len(got) > 30100:
        out.append("  [6만 자 방송] 앞·뒤를 남기고 상한 안으로 줄여야 합니다")
    return out


def check_normalize_fields() -> list[str]:
    """모델이 문자열 자리에 목록·숫자·None 을 보내도 렌더링이 죽지 않아야 한다(2026-11-13 에 6건 유실)."""
    import generate_report as g
    out = []
    data = {"title": "제목", "meta_description": ["한 줄", "요약"], "summary": None,
            "battery_implication": 7, "_transcript_source": "gemini-video", "relation": "indirect",
            "overview": {"topic": "주제", "channel": "채널", "key_figures": ["3조 원", "12%"],
                         "impact": {"a": "영향"}, "tickers": ["삼성전자", "SK하이닉스"]},
            "sections": [{"heading": ["소제목"], "body": ["문장 하나.", "문장 둘."]}, "잘못된 항목"],
            "glossary": [{"term": "HBM", "desc": ["설명"], "analogy": None}]}
    g.normalize_fields(data)
    if data["overview"]["tickers"] != "삼성전자, SK하이닉스":
        out.append(f"  [목록 → 문자열] tickers 가 {data['overview']['tickers']!r}")
    if data["summary"] != "" or data["battery_implication"] != "7":
        out.append("  [None·숫자] 문자열로 맞춰지지 않았습니다")
    if len(data["sections"]) != 1 or data["sections"][0]["body"] != "문장 하나., 문장 둘.":
        out.append("  [sections] 잘못된 항목 제거·본문 문자열화가 안 됐습니다")
    try:
        page = g.render_html(data, {"channel": "삼프로TV", "video_id": "abc"}, "2026-11-13")
        if "SK하이닉스" not in page:
            out.append("  [렌더링] 내용이 빠졌습니다")
    except Exception as exc:  # noqa: BLE001
        out.append(f"  [렌더링] 목록 필드에서 죽었습니다 — {exc.__class__.__name__}: {exc}")
    return out
