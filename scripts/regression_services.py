"""회귀 검사 — 외부 공급자·알림·워크플로 배선(텔레그램, GitHub Models, OpenAI/NVIDIA/Gemini 키, 워크플로 권한·재시도).

실행은 test_keywords.py 가 이 파일의 check_* 함수를 자동으로 모아 돌린다(수동 목록 없음).
"""
from __future__ import annotations

import re


# API 키 없는 예비 추론 경로(GitHub Models).
# 가장 중요한 성질은 '잘 되는 것'이 아니라 <없거나 실패해도 지금보다 나빠지지 않는 것>이다.
# Gemini 한도가 바닥나면 넘어가고, 예비도 막히면 예전처럼 QuotaExhausted 로 끝나야 한다.
def check_gh_fallback() -> list[str]:
    import json as _json
    import os
    import gh_models as G
    import generate_report as GR

    out = []
    saved = {k: os.environ.get(k) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
    saved_gap = GR.MIN_CALL_GAP_SEC
    # import 가 finally 안쪽에서 쓰이는 이름을 만든다. 실패하면 finally 가
    # UnboundLocalError 를 내면서 <진짜 원인>을 덮어, 검사 전체가 정체불명의
    # 크래시로 끝난다(2026-10-28 에 requests 미설치로 실제로 그랬다).
    try:
        import requests
    except ModuleNotFoundError:
        return ["  [requests 미설치 — 이 검사를 건너뜁니다] pip install -r requirements.txt"]
    saved_post = requests.post
    try:
        GR.MIN_CALL_GAP_SEC = 0
        for k in ("GITHUB_TOKEN", "GH_TOKEN"):
            os.environ.pop(k, None)

        # 토큰이 없으면 조용히 비활성 — 호출자는 원래 오류를 그대로 받는다
        G._fails = 0
        if G.available():
            out.append("  [토큰 없으면 비활성이어야 함] available()=True")
        if GR._fallback("p", "테스트") is not None:
            out.append("  [토큰 없으면 None 이어야 함] _fallback 이 값을 돌려줬습니다")

        # 토큰이 있으면 응답을 정상 파싱한다
        os.environ["GITHUB_TOKEN"] = "ghs_dummy"
        G._fails = 0

        class _Ok:
            status_code = 200
            text = '{"choices":[{"message":{"content":"{\\"ok\\":1}"}}]}'

            def json(self):
                return _json.loads(self.text)

        requests.post = lambda *a, **k: _Ok()
        if G.generate("p") != '{"ok":1}':
            out.append("  [정상 응답을 그대로 돌려줘야 함] 파싱 결과가 다릅니다")

        # 403(워크플로 권한 누락)이면 조용히 물러나 원래 오류가 살아나야 한다
        class _Denied:
            status_code = 403
            text = '{"message":"Resource not accessible by integration"}'

            def json(self):
                return _json.loads(self.text)

        requests.post = lambda *a, **k: _Denied()
        G._fails = 0
        try:
            G.generate("p")
            out.append("  [403 이면 GHModelsUnavailable 이어야 함] 예외가 안 났습니다")
        except G.GHModelsUnavailable:
            pass

        # 연속 실패하면 스스로 접는다(같은 이유로 매번 시간 버리지 않도록)
        G._fails = G.FAIL_LIMIT
        if G.available():
            out.append("  [연속 실패 후에는 접어야 함] available()=True")
    finally:
        requests.post = saved_post
        GR.MIN_CALL_GAP_SEC = saved_gap
        G._fails = 0
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return out


# GitHub 로그인 없이 바로 처리되는 경로(URL 등록·텔레그램 전송) — 2026-09-22.
# 토큰을 이 브라우저에만 저장해 API 로 이슈를 만들고 끝날 때까지 지켜보는 방식이라,
# ① 필요한 조각이 다 있는지 ② 토큰을 URL 에 실어 보내 로그에 남기지 않는지
# ③ requestSummary·requestSend 가 실제로 이 경로를 쓰는지를 확인한다.
# 실제 create→poll→close→comment 흐름 자체는 Node 로 코드를 그대로 실행해
# 네트워크를 흉내 낸 시나리오 4개(무토큰·성공·401·타임아웃)로 이미 검증했다.
def check_gh_token_flow() -> list[str]:
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent
          / "site" / "assets" / "app.js").read_text(encoding="utf-8")
    out = []
    for needle, why in (
        ("LS_GH_TOKEN", "토큰 저장 키가 없습니다"),
        ("function ghToken()", "토큰 조회 함수가 없습니다"),
        ("function configureGhToken()", "토큰 설정 UI 함수가 없습니다"),
        ("function ghApiCall(", "GitHub API 호출 함수가 없습니다"),
        ("function ghRunAndWait(", "이슈 생성·대기 함수가 없습니다"),
        ("function runOrOpenIssue(", "토큰 유무에 따라 갈라 주는 함수가 없습니다"),
    ):
        if needle not in js:
            out.append(f"  [{why}] {needle!r} 가 사라졌습니다")
    if "getElementById('gh-token-btn')" not in js:
        out.append("  [토큰 설정 버튼 배선] init() 이 gh-token-btn 을 연결하지 않습니다")

    # 토큰은 반드시 Authorization 헤더로만 보낸다 — URL 쿼리에 실으면
    # 브라우저 기록·Referer·서버 로그에 그대로 남는다.
    if "Authorization" not in js or "Bearer ${ghToken()" not in js:
        out.append("  [토큰을 Authorization 헤더로 보내지 않습니다]")
    if re.search(r"[?&]token=\$\{ghToken", js):
        out.append("  [토큰이 URL 쿼리로 새고 있습니다 — 헤더로만 보내야 합니다]")

    # requestSummary·requestSend 가 실제로 이 경로를 쓰는지 — 함수만 만들어 두고
    # 안 불러 쓰면 아무 의미가 없다. 통짜 주석 줄 속 언급까지 코드로 오인하지
    # 않도록 걷어내고 검사한다(check_name_fix_actually_fixes 와 같은 함정).
    # 줄 끝에 붙는 // 는 URL(https://...) 과 겹칠 수 있어 건드리지 않는다 —
    # '//' 로 시작하는 줄 전체만 걷어낸다.
    def _code_only(text: str) -> str:
        return "\n".join(l for l in text.splitlines() if not l.strip().startswith("//"))

    m = re.search(r"async function requestSummary\(\)[\s\S]*?\n\}", js)
    if not m or "runOrOpenIssue" not in _code_only(m.group(0)):
        out.append("  [requestSummary 가 runOrOpenIssue 를 쓰지 않습니다]")
    m = re.search(r"async function requestSend\([\s\S]*?\n\}", js)
    if not m or "runOrOpenIssue" not in _code_only(m.group(0)):
        out.append("  [requestSend 가 runOrOpenIssue 를 쓰지 않습니다]")

    # init() 을 두 번 부를 일이 없어야 한다 — '성공 후 init() 재호출'로 고치면
    # 이벤트 리스너가 중복 등록된다. reload() 로 데이터만 다시 받고, 리스너
    # 등록은 init() 에서 한 번만 하는 구조여야 한다.
    if "async function reload()" not in js:
        out.append("  [reload() 가 없습니다 — 재요청 뒤 init() 을 통째로 다시 부르면 리스너가 중복됩니다]")
    return out


# 워크플로에 권한 한 줄이 없으면 예비 경로는 403 으로 전부 실패한다.
# 코드만 있고 권한이 빠지는 조합이 가장 알아채기 어렵다.
# 텔레그램 알림이 <이차전지와 연결되는 글만> 보내는가, 그리고 <커밋 뒤>에 도는가.
#
# 두 번째가 특히 중요하다. 커밋 앞에서 보내면, 커밋이나 push 가 실패한 날
# 존재하지 않는 리포트 링크를 대화방에 뿌리게 된다.
# 시크릿이 없는 저장소에서도 파이프라인이 멀쩡히 끝나야 한다는 것도 함께 고정한다.
def check_telegram() -> list[str]:
    import os
    from pathlib import Path
    import telegram_notify as tg

    out = []
    rows = [
        {"id": "a", "relation": "direct", "title": "t", "summary": "s",
         "channel": "c", "date": "2026-09-01", "url": "a.html", "video": "v"},
        {"id": "b", "relation": "context", "title": "t", "summary": "s",
         "channel": "c", "date": "2026-09-02", "url": "b.html", "video": "v"},
        {"id": "c", "relation": "indirect", "title": "t", "summary": "s",
         "channel": "c", "date": "2026-09-03", "url": "c.html", "video": "v"},
    ]

    sent: list[str] = []
    orig_call, orig_sleep = tg._call, tg.time.sleep
    keep = {k: os.environ.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
    try:
        tg.time.sleep = lambda _s: None

        # ① 시크릿이 없으면 아무것도 보내지 않고, 예외도 내지 않는다
        for k in keep:
            os.environ.pop(k, None)
        tg._call = lambda m, p: out.append("  [시크릿 없이 전송 시도함] 네트워크를 건드렸습니다")
        if tg.send_reports(rows) != 0:
            out.append("  [시크릿 없으면 0건] 0이 아닌 값을 돌려줬습니다")

        # ② 시크릿이 있으면 direct/indirect 만 나간다 (context 는 배터리 무관)
        os.environ["TELEGRAM_BOT_TOKEN"] = "t"
        os.environ["TELEGRAM_CHAT_ID"] = "1"
        tg._call = lambda m, p: sent.append(p["text"]) or {}
        tg.send_reports(rows)
        if len(sent) != 2:
            out.append(f"  [direct·indirect 2건만 발송] {len(sent)}건 나갔습니다")
        if any("b.html" in t for t in sent):
            out.append("  [context 는 제외] 배터리와 무관한 글이 나갔습니다")

        # ③ 상한을 넘으면 <최신> 것을 남긴다 (입력은 오래된 것부터)
        sent.clear()
        many = [dict(rows[0], id=str(i), url=f"{i}.html") for i in range(5)]
        tg.MAX_PER_RUN, cap = 2, tg.MAX_PER_RUN
        tg.send_reports(many)
        tg.MAX_PER_RUN = cap
        if not (len(sent) == 2 and "3.html" in sent[0] and "4.html" in sent[1]):
            out.append("  [상한 초과 시 최신 것을 남김] 오래된 쪽이 남았습니다")
    finally:
        tg._call, tg.time.sleep = orig_call, orig_sleep
        for k, v in keep.items():
            os.environ[k] = v if v is not None else os.environ.pop(k, "")
            if not v:
                os.environ.pop(k, None)

    # ④ 알림 단계는 커밋 <뒤>에 온다 — 사이트에 올라간 것만 알려야 한다
    wf = (Path(__file__).resolve().parent.parent
          / ".github/workflows/archive.yml").read_text(encoding="utf-8")
    commit_at, notify_at = wf.find("Commit new reports"), wf.find("Notify Telegram")
    if notify_at < 0:
        out.append("  [archive.yml 에 텔레그램 알림 단계] 사라졌습니다")
    elif notify_at < commit_at:
        out.append("  [알림은 커밋 뒤] 커밋 앞으로 옮겨져 죽은 링크가 나갈 수 있습니다")
    if "TELEGRAM_BOT_TOKEN" not in wf:
        out.append("  [알림 단계에 TELEGRAM_BOT_TOKEN 전달] 사라졌습니다")

    # ⑤ 무엇이 새로 나왔는지 파이프라인이 넘겨 주는가 (알림이 읽는 통로)
    rp = (Path(__file__).resolve().parent / "run_pipeline.py").read_text(encoding="utf-8")
    if "new_ids" not in rp:
        out.append("  [run_pipeline 이 new_ids 를 기록] 사라져 알림이 보낼 것을 못 찾습니다")
    return out


# 카드의 📨 버튼이 리포트 <전문>을 보내는가.
#
# 목록 알림은 제목·요약만 보내지만 이 경로는 01~08 을 통째로 옮긴다.
# 발행 HTML 을 정규식으로 읽는 구조라, 렌더러가 바뀌면 조용히 0섹션이 되어
# '보냈다'는 말만 남고 알맹이가 빈 메시지가 나간다. 실제 발행물로 고정한다.
def check_send_report() -> list[str]:
    from pathlib import Path
    import send_report as sr
    import telegram_notify as tg
    from build_index import load_existing
    from config import NEWS_DIR

    out = []
    # ① 실제 발행물에서 섹션이 실제로 뽑히는가 (최근 것 몇 건)
    checked = 0
    for r in load_existing()[:5]:
        f = NEWS_DIR / r.get("url", "")
        if not f.exists():
            continue
        checked += 1
        secs = sr.extract_sections(f.read_text(encoding="utf-8"))
        if len(secs) < 4:
            out.append(f"  [발행물에서 01~08 을 읽어야 함] {r['id']} → {len(secs)}섹션")
            continue
        nums = [n for n, _, _ in secs]
        if "01" not in nums or "08" not in nums:
            out.append(f"  [01 핵심 개요·08 용어 사전이 있어야 함] {r['id']} → {nums}")
        if any(not lines for _, _, lines in secs):
            out.append(f"  [본문이 빈 섹션이 있음] {r['id']}")
        # ② 유튜브 링크가 반드시 들어간다
        body = "\n".join(tg.split_message(sr.build_message(r, secs)))
        if r.get("video") and r["video"] not in body:
            out.append(f"  [유튜브 링크가 빠짐] {r['id']}")
        if "<b>01." not in body:
            out.append(f"  [섹션 번호·제목이 빠짐] {r['id']}")
    if not checked:
        out.append("  [검사할 발행물을 못 찾음]")

    # ③ 메시지 상한(4096자)을 넘는 조각이 나오면 전송이 통째로 거부된다
    long_parts = ["가" * 5000, "나" * 300, "다" * 4000]
    chunks = tg.split_message(long_parts)
    if any(len(c) > tg.MAX_CHARS for c in chunks):
        out.append(f"  [한 메시지가 {tg.MAX_CHARS}자를 넘으면 안 됨] "
                   f"→ {[len(c) for c in chunks]}")
    if "".join(chunks).count("가") != 5000:
        out.append("  [나눠 보내면서 글자가 사라짐]")

    # ④ 권한은 워크플로가 지킨다 — 소유자가 연 이슈만 처리
    wf = (Path(__file__).resolve().parent.parent
          / ".github/workflows/send-report.yml").read_text(encoding="utf-8")
    if "github.event.issue.user.login == github.repository_owner" not in wf:
        out.append("  [소유자가 연 이슈만 처리해야 함] 조건이 사라졌습니다")
    if "[전송]" not in wf:
        out.append("  [제목 '[전송]' 으로 거르는 조건] 사라졌습니다")

    # ⑤ 사이트 버튼이 즐겨찾기 <왼쪽>에 있는가 (요청한 자리다)
    js = (Path(__file__).resolve().parent.parent
          / "site/assets/app.js").read_text(encoding="utf-8")
    tg_at, fav_at = js.find('icon-btn tg'), js.find('icon-btn fav')
    if tg_at < 0:
        out.append("  [카드에 텔레그램 버튼] 사라졌습니다")
    elif tg_at > fav_at:
        out.append("  [텔레그램 버튼은 즐겨찾기 왼쪽] 순서가 바뀌었습니다")
    if "requestSend" not in js:
        out.append("  [버튼 동작(requestSend)] 사라졌습니다")
    return out


def check_summarize_url_has_fallbacks() -> list[str]:
    from pathlib import Path
    wf = (Path(__file__).resolve().parent.parent
          / ".github/workflows/summarize-url.yml").read_text(encoding="utf-8")
    out = []
    for name in ("GEMINI_API_KEY_2:", "GITHUB_TOKEN:", "OPENAI_API_KEY:",
                 "OPENAI_API_KEY_2:"):
        if name not in wf:
            out.append(f"  [URL 요약도 {name[:-1]} 를 받아야 함] archive.yml 에만 있습니다")
    if "models: read" not in wf:
        out.append("  [URL 요약도 models: read 권한이 있어야 함] "
                   "없으면 GITHUB_TOKEN 을 넘겨도 GitHub Models 가 거부합니다")
    return out


#
# 둘은 한 쌍이다. 끝까지 보기로 하면 하루 예산이 훨씬 빨리 닳으므로,
# 키를 더 넣어 벌충하지 못하면 발행이 오히려 줄어든다.
def check_multi_key_and_full_video() -> list[str]:
    import importlib
    import inspect
    import os
    from pathlib import Path
    import gemini_keys
    import video_budget as vb
    import generate_report as G

    out = []
    saved = {k: os.environ.get(k) for k in os.environ
             if "GEMINI" in k or "OPENAI" in k}
    try:
        for k in list(saved):
            os.environ.pop(k, None)
        os.environ["GEMINI_API_KEY"] = "k1"
        os.environ["GEMINI_API_KEY_2"] = "k2"
        os.environ["GEMINI_API_KEY_3"] = "k1"      # 같은 키 — 한도는 하나다
        gk = importlib.reload(gemini_keys)

        if gk.count() != 2:
            out.append(f"  [같은 키는 하나로 세야 함] {gk.count()}개로 셌습니다")
        if not gk.spend_and_rotate():
            out.append("  [첫 키가 바닥나면 다음 키로 가야 함] 더 못 간다고 했습니다")
        if gk.spend_and_rotate():
            out.append("  [키를 다 쓰면 False 여야 함] 아직 남았다고 했습니다")

        # 키가 하나도 없으면 0개 — 예전처럼 GEMINI_API_KEY 만 보던 경로도 살아야 한다
        for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
            os.environ.pop(k, None)
        gk = importlib.reload(gemini_keys)
        if gk.count() != 0 or gk.current() != "":
            out.append("  [키가 없으면 0개·빈 값] 그렇지 않습니다")
    finally:
        for k in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
        importlib.reload(gemini_keys)

    # 영상 예산 — 상한 0 은 '끝까지'라는 뜻이고, 예산도 길이 전부를 잡아야 한다.
    # 여기서 0 을 '공짜'로 읽으면 하루 예산이 아무 일도 안 하게 된다.
    if vb.cost_minutes(7200, 0) != 120.0:
        out.append(f"  [상한 0 이면 길이 전부를 잡아야 함] {vb.cost_minutes(7200, 0)}")
    if vb.cost_minutes(7200, 40) != 40.0:
        out.append("  [상한이 있으면 그 값으로 잘라야 함]")
    if vb.cost_minutes(None, 0) <= 0:
        out.append("  [길이를 몰라도 0 분으로 잡으면 안 됨]")

    # 기본값이 '끝까지'인가 — 여기에 숫자가 다시 박히면 뒷부분을 또 잃는다
    if G.VIDEO_MAX_MINUTES != 0:
        out.append(f"  [영상은 기본이 끝까지여야 함] 지금 {G.VIDEO_MAX_MINUTES}분에서 끊깁니다")
    src = inspect.getsource(G._generate_from_video)
    if "end_offset" in src and "VIDEO_MAX_MINUTES > 0" not in src:
        out.append("  [상한이 없을 때는 end_offset 을 넣지 말아야 함]")

    # 쿼터로 접기 전에 키를 갈아타는가 (갈아타기가 빠지면 키를 넣어도 소용없다)
    gen = inspect.getsource(G._generate)
    if "rotate_key" not in gen:
        out.append("  [텍스트 한도 소진 시 키를 갈아타야 함] 갈아타기가 없습니다")
    vid = inspect.getsource(G._generate_from_video)
    if "rotate_key" not in vid:
        out.append("  [영상 한도 소진 시 키를 갈아타야 함] 갈아타기가 없습니다")

    # OpenAI 는 <마지막> 예비다 — 유일하게 과금되므로 무료 경로보다 뒤여야 한다
    fb = inspect.getsource(G._fallback)
    if "openai_models" not in fb:
        out.append("  [OpenAI 예비 경로] 연결이 없습니다")
    elif fb.find("gh_models.available") > fb.find("openai_models"):
        out.append("  [무료 경로를 먼저 써야 함] OpenAI 가 앞에 있습니다")

    # 전체 순서 — GitHub Models → NVIDIA → Gemini(텍스트) / Gemini 실패 시
    # GitHub Models → NVIDIA → OpenAI(마지막, 과금). 사용자 지정(2026-10-28).
    if "nvidia_models" not in fb:
        out.append("  [NVIDIA 예비 경로] _fallback 에 연결이 없습니다")
    elif not (fb.find("gh_models.available") < fb.find("nvidia_models")
             < fb.find("openai_models")):
        out.append("  [예비 경로 순서] GitHub Models → NVIDIA → OpenAI 순서가 아닙니다")
    if "nvidia_models" not in gen:
        out.append("  [NVIDIA] 텍스트 주경로(_generate)에 연결이 없습니다")
    elif not (gen.find("gh_models.available") < gen.find("nvidia_models")
             < gen.find("cfg = types.GenerateContentConfig")):
        out.append("  [NVIDIA 는 GitHub Models 다음·Gemini 호출 이전이어야 함] 순서가 다릅니다")

    # 워크플로가 키들을 실제로 넘기는가
    wf = (Path(__file__).resolve().parent.parent
          / ".github/workflows/archive.yml").read_text(encoding="utf-8")
    for name in ("GEMINI_API_KEY_2:", "NVIDIA_API_KEY:", "NVIDIA_API_KEY_2:",
                 "OPENAI_API_KEY:", "OPENAI_API_KEY_2:"):
        if name not in wf:
            out.append(f"  [워크플로가 {name[:-1]} 를 넘겨야 함] 사라졌습니다")
    return out


# OpenAI 도 Gemini 와 같은 규칙(KEY, KEY_2, KEY_3 …)으로 여러 개를 돌려쓰는가.
#   밑줄 없는 KEY1·KEY2 로 등록하면 인식되지 않는다 — 사용자가 실제로 헷갈렸던
#   지점이라(2026-10-28), 이름 규칙과 로테이션 둘 다 고정해 둔다.
def check_openai_multi_key() -> list[str]:
    import importlib
    import os
    import types
    import openai_models as om

    out = []
    saved = {k: os.environ.get(k) for k in os.environ if "OPENAI" in k}
    try:
        for k in list(saved):
            os.environ.pop(k, None)

        # ① 밑줄 없는 이름은 인식되지 않아야 한다 (사용자가 실제로 시도했던 형태)
        os.environ["OPENAI_API_KEY1"] = "sk-wrong"
        om2 = importlib.reload(om)
        if om2.key_count() != 0:
            out.append("  [밑줄 없는 KEY1 은 인식되면 안 됨] 등록된 것으로 셌습니다")
        os.environ.pop("OPENAI_API_KEY1", None)

        # ② KEY, KEY_2, KEY_3 — 중복은 하나로
        os.environ["OPENAI_API_KEY"] = "sk-aaa"
        os.environ["OPENAI_API_KEY_2"] = "sk-bbb"
        os.environ["OPENAI_API_KEY_3"] = "sk-aaa"
        om2 = importlib.reload(om)
        if om2.key_count() != 2:
            out.append(f"  [같은 키는 하나로 세야 함] {om2.key_count()}개로 셌습니다")

        # ③ 401/429 를 받으면 다음 키로 갈아타고, 성공하면 결과를 돌려준다
        calls = []

        class _Resp:
            def __init__(self, status, body="{}"):
                self.status_code, self.text = status, body
            def json(self):
                import json as _j
                return _j.loads(self.text)

        seq = [_Resp(429), _Resp(200, '{"choices":[{"message":{"content":"{\\"ok\\":1}"}}]}')]

        def fake_post(*a, **k):
            calls.append(k["headers"]["Authorization"])
            return seq.pop(0)

        om2.requests = types.SimpleNamespace(post=fake_post)
        import sys
        sys.modules["requests"] = om2.requests
        result = om2.generate("p")
        if result != '{"ok":1}':
            out.append(f"  [성공 응답을 그대로 돌려줘야 함] {result!r}")
        if calls != ["Bearer sk-aaa", "Bearer sk-bbb"]:
            out.append(f"  [429 면 다음 키로 갈아타야 함] 호출 순서 {calls}")

        # ④ 모든 키가 막히면 예외를 올린다 (조용히 사라지면 안 된다)
        seq2 = [_Resp(429), _Resp(429)]
        om2.requests.post = lambda *a, **k: seq2.pop(0)
        try:
            om2.generate("p")
            out.append("  [키를 다 쓰면 예외를 올려야 함] 조용히 통과했습니다")
        except om2.OpenAIUnavailable:
            pass
    finally:
        for k in list(os.environ):
            if "OPENAI" in k:
                os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
        importlib.reload(om)
    return out


# NVIDIA 도 같은 규칙(KEY, KEY_2 …)으로 여러 개를 돌려쓰는가. OpenAI 와 코드
# 모양이 같지만 엔드포인트·모델이 다르므로 설정값 자체도 함께 확인한다.
def check_nvidia_multi_key() -> list[str]:
    import importlib
    import os
    import types
    import nvidia_models as nvm

    out = []
    if "integrate.api.nvidia.com" not in nvm.ENDPOINT:
        out.append(f"  [NVIDIA 엔드포인트가 아님] {nvm.ENDPOINT}")
    saved = {k: os.environ.get(k) for k in os.environ if "NVIDIA" in k}
    try:
        for k in list(saved):
            os.environ.pop(k, None)

        # ① 밑줄 없는 이름은 인식되지 않아야 한다
        os.environ["NVIDIA_API_KEY1"] = "nvapi-wrong"
        nvm2 = importlib.reload(nvm)
        if nvm2.key_count() != 0:
            out.append("  [밑줄 없는 KEY1 은 인식되면 안 됨] 등록된 것으로 셌습니다")
        os.environ.pop("NVIDIA_API_KEY1", None)

        # ② KEY, KEY_2, KEY_3 — 중복은 하나로
        os.environ["NVIDIA_API_KEY"] = "nvapi-aaa"
        os.environ["NVIDIA_API_KEY_2"] = "nvapi-bbb"
        os.environ["NVIDIA_API_KEY_3"] = "nvapi-aaa"
        nvm2 = importlib.reload(nvm)
        if nvm2.key_count() != 2:
            out.append(f"  [같은 키는 하나로 세야 함] {nvm2.key_count()}개로 셌습니다")

        # ③ 429 를 받으면 다음 키로 갈아타고, response_format 을 강제하지 않는다
        #    (NIM 뒤 모델마다 json_object 지원 여부가 달라, 강제하면 400 이 날 수 있다)
        calls = []

        class _Resp:
            def __init__(self, status, body="{}"):
                self.status_code, self.text = status, body
            def json(self):
                import json as _j
                return _j.loads(self.text)

        seq = [_Resp(429), _Resp(200, '{"choices":[{"message":{"content":"{\\"ok\\":1}"}}]}')]

        def fake_post(*a, **k):
            calls.append((k["headers"]["Authorization"], "response_format" in k["json"]))
            return seq.pop(0)

        nvm2.requests = types.SimpleNamespace(post=fake_post)
        import sys
        sys.modules["requests"] = nvm2.requests
        result = nvm2.generate("p")
        if result != '{"ok":1}':
            out.append(f"  [성공 응답을 그대로 돌려줘야 함] {result!r}")
        if [c[0] for c in calls] != ["Bearer nvapi-aaa", "Bearer nvapi-bbb"]:
            out.append(f"  [429 면 다음 키로 갈아타야 함] 호출 순서 {calls}")
        if any(c[1] for c in calls):
            out.append("  [response_format 을 강제하면 안 됨] NIM 모델마다 지원이 달라 400 위험")

        # ④ 모든 키가 막히면 예외를 올린다
        seq2 = [_Resp(429), _Resp(429)]
        nvm2.requests.post = lambda *a, **k: seq2.pop(0)
        try:
            nvm2.generate("p")
            out.append("  [키를 다 쓰면 예외를 올려야 함] 조용히 통과했습니다")
        except nvm2.NvidiaUnavailable:
            pass
    finally:
        for k in list(os.environ):
            if "NVIDIA" in k:
                os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
        importlib.reload(nvm)
    return out


def check_key_ring() -> list[str]:
    """공급자 공통 키 돌려쓰기 규칙 — 이름 규칙·중복·순서·소진·로그에 키 비노출."""
    import os
    from key_ring import KeyRing
    import gemini_keys, openai_models, nvidia_models
    out = []
    names = ("KR_X", "KR_X_2", "KR_X_3", "KR_X3", "KR_X_CSV")
    saved = {k: os.environ.pop(k, None) for k in names}
    try:
        if KeyRing("KR_X").count() != 0 or KeyRing("KR_X").summary() != "등록된 키 없음":
            out.append("  [키 없음] 0개·'등록된 키 없음' 이어야 합니다")
        os.environ.update({"KR_X": "k1", "KR_X_2": "k2", "KR_X_3": "k1", "KR_X3": "bad", "KR_X_CSV": "c1, k2"})
        r = KeyRing("KR_X", csv_env="KR_X_CSV", noun="소진")
        if r.keys() != ["c1", "k2", "k1"]:
            out.append(f"  [수집 규칙] CSV→기본→번호 순, 중복 제거, 밑줄 없는 이름 무시여야 하는데 {r.keys()}")
        if r.current() != "c1" or not r.rotate() or r.current() != "k2":
            out.append("  [회전] 첫 키 소진 뒤 두 번째 키로 가야 합니다")
        if not r.rotate() or r.rotate():
            out.append("  [소진] 마지막 키까지 쓰면 False 여야 합니다")
        if r.spent() != 3 or "3개 소진" not in r.summary():
            out.append(f"  [요약] 소진 개수·단어가 틀립니다: {r.summary()}")
        if any(k in r.label() + r.summary() for k in ("c1", "k1", "k2")):
            out.append("  [로그] 키 값이 노출됩니다")
    finally:
        for k in names:
            os.environ.pop(k, None)
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    for mod, want in ((gemini_keys, "GEMINI_API_KEY"), (openai_models, "OPENAI_API_KEY"),
                      (nvidia_models, "NVIDIA_API_KEY")):
        if mod._ring.base != want or mod._ring.max_keys != 10:
            out.append(f"  [{mod.__name__}] KeyRing 설정이 {want}·10 이 아닙니다")
    return out


def check_workflow_models_perm() -> list[str]:
    from pathlib import Path
    wf = Path(__file__).resolve().parent.parent / ".github/workflows/archive.yml"
    text = wf.read_text(encoding="utf-8")
    out = []
    if "models: read" not in text:
        out.append("  [워크플로에 'models: read' 권한이 있어야 함] 사라졌습니다")
    if "GITHUB_TOKEN" not in text:
        out.append("  [파이프라인 단계에 GITHUB_TOKEN 을 넘겨야 함] 사라졌습니다")
    return out


# 워크플로가 리포트를 push 하지 못해 통째로 잃는 일을 막는 장치.
# 2026-08-11 아침 실행이 실제로 이렇게 날아갔다 — 커밋까지 다 해 놓고
# 마지막 push 한 줄에서 'fetch first' 로 거부당해 그 실행의 결과물이 전부 버려졌다.
# 실행 도중 사람이 main 에 커밋하면 언제든 재현되는 상황이다.
def check_workflow_push_retry() -> list[str]:
    from pathlib import Path
    wf = (Path(__file__).resolve().parent.parent
          / ".github/workflows/archive.yml").read_text(encoding="utf-8")
    out = []
    for needle, why in (
        ("git fetch origin main", "push 거부 시 원격을 받아 와야 한다"),
        ("git rebase origin/main", "받아 온 것을 붙여야 한다"),
        ("rebase --abort", "충돌 시 깨끗이 되돌려야 한다"),
    ):
        if needle not in wf:
            out.append(f"  [{why}] {needle!r} 가 사라졌습니다")
    # 예약이 걸러졌을 때를 대비해 하루 여러 번 돌아야 한다
    if wf.count("- cron:") < 8:
        out.append("  [예약을 넉넉히] GitHub 는 예약을 건너뛸 수 있어 3시간 간격(8회)이어야 합니다")
    return out


# URL 직접 등록이 '성공했다'고 말해 놓고 실제로는 커밋되지 않던 사고를 막는다.
# 2026-09-17: 이슈 #10 에서 '명칭 검사' 가 (이 리포트와 무관한, 사이트 어딘가에
# 남아 있던 옛 이름 하나 때문에) 실패하자 'if 조건 없는' 커밋 단계가 통째로
# skip 됐다. 그런데 '결과 댓글' 단계는 그걸 모르고 summarize 단계의 출력만
# 보고 "✅ 요약 완료"에 리포트 링크까지 달아 이슈를 닫아 버렸다 — 그 링크는
# 존재하지 않는 페이지였다. archive.yml 의 '커밋은 always(), 명칭검사는 경고만'
# 원칙과 어긋난 상태였다.
def check_workflow_url_comment_honesty() -> list[str]:
    from pathlib import Path
    wf = (Path(__file__).resolve().parent.parent
          / ".github/workflows/summarize-url.yml").read_text(encoding="utf-8")
    out = []
    # 1) 커밋 단계가 archive.yml 과 같은 원칙(always)이어야, 이 리포트와 무관한
    #    옛 위반 하나가 새 등록을 영영 막는 일이 재발하지 않는다
    import re as _re
    m = _re.search(r"- name: Commit new report\n((?:.+\n)+?)\n", wf)
    commit_block = m.group(1) if m else ""
    if "if: always()" not in commit_block:
        out.append("  [Commit new report 단계에 if: always() 가 없습니다 — "
                    "무관한 옛 명칭 위반이 새 등록을 다시 막을 수 있습니다]")
    if 'id: commit' not in commit_block:
        out.append("  [Commit new report 단계에 id: commit 이 없습니다]")
    if "committed=" not in commit_block or "GITHUB_OUTPUT" not in commit_block:
        out.append("  [커밋 단계가 실제로 커밋했는지를 출력으로 남기지 않습니다]")
    # 2) 결과 댓글이 그 출력을 실제로 확인해야 한다 — summarize 의 자기 신고만
    #    믿으면 커밋이 안 됐어도 성공했다고 말해 버린다
    if "steps.commit.outputs.committed" not in wf:
        out.append("  [결과 댓글이 steps.commit.outputs.committed 를 확인하지 않습니다]")
    return out


def check_writer_concurrency() -> list[str]:
    """reports.json 을 쓰는 워크플로는 같은 concurrency 그룹이어야 서로 충돌하지 않는다."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / ".github/workflows"
    out = []
    for name in ("archive", "summarize-url", "delete-report"):
        t = (root / f"{name}.yml").read_text(encoding="utf-8")
        if "group: site-data-writer" not in t:
            out.append(f"  [{name}.yml] site-data-writer 동시성 그룹이 없습니다 — "
                       "동시 실행 시 reports.json 이 충돌합니다")
    return out
