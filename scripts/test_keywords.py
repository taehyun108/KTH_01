"""키워드 매칭 회귀 테스트 (LLM·네트워크 없이 즉시 실행).

목적:
  1. 국내 정책(세액공제·특별법 등)·통상(관세) 영상이 후보로 잡히는지
  2. 채널 상용구/해시태그만 있는 무관한 영상이 걸러지는지
왜 필요한가: 키워드를 손볼 때마다 한쪽을 고치면 다른 쪽이 조용히 망가졌다.
CI 에서 매번 돌려 회귀를 즉시 잡는다.

실행: python scripts/test_keywords.py
"""
from __future__ import annotations

import sys

from fetch_history import is_short
from fetch_rss import match_candidate

# 채널 설명글에 늘 붙는 상용구 — 이것만으로는 절대 후보가 되면 안 된다
BOILERPLATE = (
    "경제를 쉽게 풀어주는 채널입니다. 구독과 좋아요 부탁드려요! "
    "비즈니스 문의: biz@example.com "
    "#경제 #투자 #주식 #금리 #전기차 #데이터센터 #관세 #부동산 #재테크"
)

# (제목, 설명, 후보로 잡혀야 하는가)
CASES: list[tuple[str, str, bool]] = [
    # ── 국내 정책 (그동안 통째로 누락되던 영역) ──────────────────────────
    ("국내생산세액공제 도입, 우리 제조업엔 어떤 의미일까", "", True),
    ("정부, 통합투자세액공제 확대…기업 부담 얼마나 줄까", "", True),
    ("국가첨단전략산업 특별법 국회 통과", "", True),
    ("K-칩스법 연장 결정, 반도체·배터리 업계 반응은", "", True),
    ("전력수급기본계획 확정…산업용 전기요금은", "", True),
    ("[속보] 오늘 국무회의 주요 안건 정리", "", True),
    ("기획재정부 세제개편안 발표", "", True),
    ("중대재해처벌법 개정 논의 본격화", "", True),
    # 설명글에만 정책어가 있는 경우도 잡아야 한다
    ("오늘의 경제 브리핑", BOILERPLATE + " 이번 편은 국내생산세액공제를 다룹니다.", True),
    ("주간 이슈 정리", BOILERPLATE + " 조세특례제한법 개정안을 살펴봅니다.", True),

    # ── 통상·관세 ────────────────────────────────────────────────────
    ("트럼프 상호관세 발표, 한국 경제 영향은", "", True),
    ("미국 무역확장법 232조 조사 착수", "", True),
    ("중국 희토류 수출 통제 확대", "", True),
    ("반덤핑 관세 부과 결정", "", True),
    ("New Section 301 Tariffs on Chinese EVs", "", True),
    ("오늘의 시장", BOILERPLATE + " 이번 상호관세 조치를 자세히 다룹니다.", True),

    # ── 배터리 직접 ──────────────────────────────────────────────────
    ("LG에너지솔루션 2분기 실적 발표", "", True),
    ("전고체 배터리 양산 로드맵", "", True),
    ("Why LFP batteries are winning", "", True),
    ("신제품 소개", BOILERPLATE + " 이번 영상은 양극재 공정을 다룹니다.", True),

    # ── 응용분야 ─────────────────────────────────────────────────────
    ("AI 데이터센터 전력난, ESS가 답일까", "", True),
    ("전기차 캐즘 언제 끝나나", "", True),

    # ── 거시 ─────────────────────────────────────────────────────────
    ("연준 FOMC 금리 동결", "", True),
    ("Federal Reserve holds interest rates steady", "", True),

    # ── 무관 (반드시 걸러져야 함) ─────────────────────────────────────
    ("클래식 음악 감상법 10가지", BOILERPLATE, False),
    ("초보자를 위한 홈트레이닝 루틴", BOILERPLATE, False),
    ("우주의 크기는 얼마나 될까? 천문학 이야기", BOILERPLATE, False),
    ("맛집 탐방 - 서울 3대 냉면", BOILERPLATE, False),
    ("영어 회화 공부법", BOILERPLATE, False),
    ("How to develop better habits", BOILERPLATE, False),
    ("The business of Hollywood movies", BOILERPLATE, False),

    # ── 일상어와 겹쳐 오검출되기 쉬운 낱말 (증세=병세, 인증=본인인증 …) ────
    ("감기 증세가 심할 때 대처법", "", False),
    ("고혈압 초기 증세 자가진단", "", False),
    ("본인인증 없이 가입하는 법", "", False),
    ("인증샷 잘 찍는 꿀팁", "", False),
    ("미식축구 쿼터백 이야기", "", False),
    ("물가에 앉아 낚시하기", "", False),
    # …그래도 진짜 경제 문맥은 놓치지 않아야 한다
    ("정부 증세 논의 본격화", "", True),
    ("소비자물가 3개월 만에 반등", "", True),
    ("수입 쿼터 확대 결정", "", True),
    ("배터리 안전인증 기준 강화", "", True),
]


# (길이초, 제목, 쇼츠인가)
SHORTS_CASES: list[tuple[object, str, bool]] = [
    (45, "배터리 3사 실적 요약", True),          # 45초 → 쇼츠
    (180, "관세 한 방에 정리", True),            # 3분 정각 → 쇼츠 상한
    (181, "관세 완전 분석", False),              # 3분 1초 → 본편
    (1800, "이차전지 산업 30분 심층 분석", False),
    (None, "전고체 배터리 총정리 #shorts", True),  # 길이 모름 + 표식
    (None, "전고체 배터리 총정리", False),         # 길이 모름 + 표식 없음 → 본편으로 봄
    (None, "리튬 가격 정리 #쇼츠", True),
    (0, "라이브 다시보기", False),                # 길이 0(미상) → 본편으로 봄
]


# (문장, 옛 명칭으로 잡혀야 하는가)
# 병기 표기('옛이름(현 새이름)')는 프롬프트가 지시하고 --fix 도 만들어 내는 <정상> 형태다.
# 예전에는 이것까지 오류로 잡아서, 고치면 고칠수록 검사가 실패하는 상태였다.
NAME_CASES: list[tuple[str, bool]] = [
    ("기획재정부가 세제개편안을 발표했습니다", True),
    ("기획재정부(현 재정경제부)가 세제개편안을 발표했습니다", False),
    ("재정경제부(옛 기획재정부)가 세제개편안을 발표했습니다", False),
    ("재정경제부가 세제개편안을 발표했습니다", False),
    ("환경부 장관이 참석했습니다", True),
    ("기후에너지환경부 장관이 참석했습니다", False),   # 새 이름 안에 옛 이름이 들어 있는 경우
    ("포스코케미칼이 증설합니다", True),
    ("포스코퓨처엠(구 포스코케미칼)이 증설합니다", False),
    ("한국아트라스비엑스가 납축전지를 만듭니다", True),
    ("한국앤컴퍼니(옛 한국아트라스비엑스)가 납축전지를 만듭니다", False),
]


def check_names() -> list[str]:
    from org_names import find_outdated
    out = []
    for text, expect in NAME_CASES:
        got = bool(find_outdated(text))
        if got != expect:
            want = "옛 명칭으로 잡혀야" if expect else "정상으로 통과돼야"
            out.append(f"  [{want} 함] {text!r} → {find_outdated(text)}")
    return out


# (자막 출처, '무관' 판정을 영구로 남겨도 되는가)
# 설명글 200자만 보고 내린 '무관'을 영구 배제하면, 나중에 자막이 열려도 그 영상은
# 영영 다시 보지 않는다. 자막을 확보한 상태의 판단만 영구로 남겨야 한다.
EVIDENCE_CASES: list[tuple[str, bool]] = [
    ("youtube-transcript-api", True),
    ("yt-dlp-captions", True),
    ("gemini-video", True),
    ("local-cache", True),          # 집 PC 가 받아 둔 자막
    ("video-description", False),   # 설명글만
    ("unavailable", False),
    ("", False),
]


def check_evidence() -> list[str]:
    import seen_store as ss
    out = []
    for src, permanent in EVIDENCE_CASES:
        got = ss.irrelevant_reason(src)
        want = ss.REASON_IRRELEVANT if permanent else ss.REASON_IRRELEVANT_WEAK
        if got != want:
            out.append(f"  [{'영구' if permanent else '재확인'}이어야 함] "
                       f"출처 {src!r} → {got}")
    return out


# (오류 메시지, '이 모델은 못 쓴다'로 판정해 다른 모델로 바꿔야 하는가)
# 2026-08-10: models.list() 에 있어서 고른 모델이 정작 호출하면 404 를 냈고,
# 그 처리가 없어 한 실행에서 19건이 전부 실패했다. 판정 로직을 고정해 둔다.
MODEL_ERR_CASES: list[tuple[str, bool]] = [
    ("404 NOT_FOUND. {'error': {'code': 404, 'message': 'This model "
     "models/gemini-2.5-flash is no longer available to new users.'}}", True),
    ("404 NOT_FOUND models/foo not found", True),
    ("429 RESOURCE_EXHAUSTED GenerateRequestsPerDayPerProject", False),
    ("503 UNAVAILABLE The model is overloaded", False),
    ("500 INTERNAL", False),
    ("400 INVALID_ARGUMENT Unsupported MIME type: text/html", False),
]


def check_model_errors() -> list[str]:
    from generate_report import _is_model_gone
    out = []
    for msg, expect in MODEL_ERR_CASES:
        got = _is_model_gone(msg)
        if got != expect:
            want = "모델 교체" if expect else "그대로 처리"
            out.append(f"  [{want} 이어야 함] {msg[:56]!r} → {got}")
    return out


# 자막이 새로 생겼을 때 '다시 볼 사유'가 실제로 풀리는가.
# 2026-08-10: 해제 로직이 '근거부족'만 보고 있어서, 정작 자막이 생기면 뒤집힐
# '무관(설명글만 보고 판단)' 21건이 7일간 묶여 있었다. 두 사유 모두 풀려야 한다.
UNBLOCK_CASES: list[tuple[str, bool]] = [
    ("근거부족", True),
    ("무관(설명글만 보고 판단)", True),
    ("무관", False),          # 자막을 보고 내린 판단 — 영구
]


def check_unblock() -> list[str]:
    import seen_store as ss
    out = []
    for reason, should_free in UNBLOCK_CASES:
        got = reason in ss.RETRYABLE
        if got != should_free:
            want = "자막 생기면 해제" if should_free else "영구 배제"
            out.append(f"  [{want} 여야 함] {reason!r} → RETRYABLE={got}")
    return out


# 처리 우선순위 — 하루 쿼터가 빠듯해 뒤쪽은 손도 못 대므로 순서가 곧 발행량이다.
# 자막 캐시가 있는 후보(근거 최상·쿼터 최소)가 반드시 맨 앞이어야 한다.
def check_priority() -> list[str]:
    from run_pipeline import order_candidates

    fresh = [
        {"video_id": "NODESC", "channel": "A", "description": "", "published": "3"},
        {"video_id": "CACHED", "channel": "B", "description": "", "published": "1"},
        {"video_id": "DESC", "channel": "A", "description": "x" * 300, "published": "2"},
    ]
    got = [c["video_id"] for c in order_candidates(fresh, float("inf"),
                                                   has_cache={"CACHED"}.__contains__)]
    want = ["CACHED", "DESC", "NODESC"]
    if got != want:
        return [f"  [처리 순서가 {want} 여야 함] → {got}"]
    return []


# 집 PC 자막 수집 스크립트의 git 처리.
# 2026-08-10 모의 실행에서 세 가지가 드러났다. 전부 '첫 실행이 그냥 실패'하는 종류라
# 사람이 눈치채기 전에 하루를 날린다. 코드에 그 장치가 남아 있는지 확인한다.
#   · 원격이 앞서 있으면(봇이 하루 2회 커밋) pull 없이 push 하면 거부당한다
#   · 트리에 미커밋 변경이 있으면 rebase 자체가 거부된다 → --autostash
#   · 커밋만 되고 push 가 막힌 뒤 재실행하면 '변경 없음'으로 끝나 영영 안 올라간다
def check_local_push() -> list[str]:
    import inspect
    import fetch_transcripts_local as F

    out = []
    src = inspect.getsource(F)
    for needle, why in (
        ("fetch", "push 전에 원격을 받아 와야 한다"),
        ("--autostash", "미커밋 변경이 있어도 rebase 되게 해야 한다"),
        ("rev-list", "못 올린 커밋이 남았는지 확인해야 한다"),
    ):
        if needle not in src:
            out.append(f"  [{why}] {needle!r} 가 사라졌습니다")
    if "_sync_and_push" not in src:
        out.append("  [push 는 _sync_and_push 를 거쳐야 함] 함수가 사라졌습니다")
    return out


# 쿼터 양보 — 신규 발행과 말투 교체가 하루 쿼터를 나눠 쓰는 규칙.
# 사람이 REGEN_MAX 를 손으로 맞추던 방식은 어느 쪽으로 맞춰도 절반은 손해였다.
#   (left, quota_hit, REGEN_MAX, 재생성이 돌아야 하는가)
HANDOFF_CASES: list[tuple[int, bool, str, bool]] = [
    (12, True, "", False),    # 신규가 쿼터에 막혀 남았다 → 양보
    (5, False, "", False),    # 시간 상한으로 남았다 → 양보
    (0, False, "", True),     # 신규가 후보를 다 처리했다 → 남는 쿼터 사용
    (0, False, "0", False),   # 사람이 명시적으로 껐다 → 무조건 끔
]


def check_handoff() -> list[str]:
    import os
    import run_pipeline as R

    out = []
    saved = {k: os.environ.get(k) for k in ("REGEN_MAX", "REGEN_MAX_IDLE")}
    try:
        for left, hit, regen_max, should_run in HANDOFF_CASES:
            R.write_state(left=left, new=0, quota_hit=hit)
            state = R.read_state()
            limit = int(regen_max) if regen_max.strip() else None
            # regenerate.py 와 같은 판정
            runs = not (limit == 0
                        or state.get("quota_hit") or state.get("left", 0) > 0)
            if runs != should_run:
                want = "돌아야" if should_run else "건너뛰어야"
                out.append(f"  [{want} 함] left={left} quota_hit={hit} "
                           f"REGEN_MAX={regen_max!r} → 실행={runs}")
    finally:
        R.STATE_FILE.unlink(missing_ok=True)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return out


# '오늘 못 본 것'과 '이 영상은 근거가 없다'를 가르는가.
# 2026-08-10: 모델이 404 를 뱉던 실행에서 처리 못 한 94건이 전부 '근거부족'으로
# 기록됐고, 그건 7일짜리 차단이라 모델이 고쳐진 뒤에도 일주일간 묻혔다.
# 앞엣것은 판정으로 남기면 안 된다.
TRANSIENT_CASES: list[tuple[str, bool]] = [
    ("404 NOT_FOUND models/gemini-2.5-flash is no longer available", True),
    ("429 RESOURCE_EXHAUSTED quota exceeded", True),
    ("503 UNAVAILABLE The model is overloaded", True),
    ("500 INTERNAL", True),
    ("Deadline exceeded", True),
    ("400 INVALID_ARGUMENT: video is private", False),
    ("This video is age-restricted", False),
    ("", False),
]


def check_transient() -> list[str]:
    from generate_report import _is_transient, NotAttempted, InsufficientContext
    out = []
    if not issubclass(NotAttempted, InsufficientContext):
        out.append("  [NotAttempted 는 InsufficientContext 의 하위여야 함] "
                   "그래야 기존 처리 경로가 그대로 안전하다")
    for msg, expect in TRANSIENT_CASES:
        got = _is_transient(msg)
        if got != expect:
            want = "보류(판정 안 남김)" if expect else "근거부족으로 기록"
            out.append(f"  [{want} 이어야 함] {msg[:52]!r} → {got}")
    return out


# 429 응답에서 '하루 몇 건까지인가'를 실제로 읽어 내는가.
# 이 숫자가 곧 하루 발행량의 상한인데, 파서가 JSON 형태만 보고 있어서
# 정작 구글이 산문으로 적어 보낸 'limit: 20' 을 놓치고 '상세 미확인'만 찍었다.
# 그 20 을 몰라서 며칠 동안 엉뚱한 곳을 고쳤다.
def check_quota_parse() -> list[str]:
    from generate_report import quota_detail
    prose = ("429 RESOURCE_EXHAUSTED ... * Quota exceeded for metric: "
             "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
             "limit: 20, model: gemini-3.6-flash\nPlease retry in 55.1s.")
    got = quota_detail(prose)
    out = []
    if "20" not in got:
        out.append(f"  [상한 20 을 읽어야 함] → {got}")
    if "gemini-3.6-flash" not in got:
        out.append(f"  [모델명을 읽어야 함] → {got}")

    js = ('{"quotaId": "GenerateRequestsPerDayPerProjectPerModel", '
          '"quotaValue": "250"}')
    got2 = quota_detail(js)
    if "250" not in got2:
        out.append(f"  [JSON 형태도 계속 읽어야 함] → {got2}")
    return out


# 모델은 '똑똑한 순서'가 아니라 <무료 한도가 큰 순서>로 골라야 한다.
# gemini-flash-latest(=gemini-3.6-flash)는 하루 20건이라 이걸 먼저 고르면
# 무관 판정 몇 건만 나와도 발행이 0건이 된다. Lite 계열이 앞에 와야 한다.
def check_model_order() -> list[str]:
    from generate_report import _MODEL_PREFS
    out = []
    prefs = list(_MODEL_PREFS)
    try:
        lite = min(i for i, m in enumerate(prefs) if "lite" in m)
        latest = prefs.index("gemini-flash-latest")
    except ValueError:
        return ["  [선호 목록에 lite 계열과 gemini-flash-latest 가 모두 있어야 함]"]
    if lite > latest:
        out.append(f"  [Lite 계열이 gemini-flash-latest 보다 앞이어야 함] "
                   f"lite={lite} latest={latest}")
    return out


# 쪽지가 없을 때(파이프라인이 도중에 죽었거나 단독 실행) 재생성이 무제한으로
# 돌면 안 된다. 하루 쿼터가 20건 남짓이라 한 번 무제한으로 돌면 그날 신규 발행이
# 0 이 된다. 예전에는 워크플로가 REGEN_MAX=0 으로 막아 이 구멍이 안 보였다.
def check_regen_guard() -> list[str]:
    import inspect
    import regenerate
    src = inspect.getsource(regenerate.regenerate)
    out = []
    if "elif limit is None:" not in src:
        out.append("  [쪽지 없음 + REGEN_MAX 미설정 → 보수적 상한] 안전장치가 사라졌습니다")
    if "REGEN_MAX_IDLE" not in src:
        out.append("  [남는 쿼터 상한] REGEN_MAX_IDLE 처리가 사라졌습니다")
    return out


# 멈춘 이유를 정확히 적는가. 쿼터로 멈춘 실행을 '시간 상한'이라고 찍으면
# 76초 만에 끝난 실행이 '35분 상한에 걸렸다'고 말하게 된다.
# 원인을 잘못 가리키는 로그는 없는 로그보다 나쁘다 — 실제로 그 때문에 헤맸다.
def check_stop_reason() -> list[str]:
    import inspect
    import run_pipeline
    src = inspect.getsource(run_pipeline.main)
    if "일일 쿼터 소진" not in src or "quota_hit else" not in src:
        return ["  [멈춘 이유를 쿼터/시간으로 구분해 찍어야 함] 구분이 사라졌습니다"]
    return []


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
    try:
        import requests
        saved_post = requests.post
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


# 워크플로에 권한 한 줄이 없으면 예비 경로는 403 으로 전부 실패한다.
# 코드만 있고 권한이 빠지는 조합이 가장 알아채기 어렵다.
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


# 쇼츠가 RSS 를 타고 되살아나지 않는가.
#
# 2026-08-11 사고: 쇼츠 필터는 RSS·yt-dlp 양쪽에 다 있었는데도 쇼츠가 발행됐다.
#   · RSS 에는 영상 길이가 없어 '#shorts' 표식 없는 쇼츠를 못 거른다
#   · 길이를 아는 것은 yt-dlp 열거뿐인데
#   · run_pipeline 이 설명글을 살리려고 RSS 쪽으로 덮어쓰면서
#     길이로 걸러 낸 판단이 통째로 뒤집혔다
# '필터가 있다'와 '필터가 이긴다'는 다르다. 후자를 고정한다.
def check_shorts_not_revived() -> list[str]:
    import fetch_history

    saved = set(fetch_history.SHORT_IDS)
    try:
        fetch_history.SHORT_IDS.clear()
        # 길이를 아는 쪽(yt-dlp)이 '쇼츠'로 판정한 상태를 만든다
        fetch_history.SHORT_IDS.add("SHORTVID")

        # 병합 재현 — hist 는 쇼츠를 뺐고, RSS 는 표식이 없어 그대로 들고 있다
        hist = [{"video_id": "NORMAL", "channel": "A", "title": "본편",
                 "description": "", "published": "2026-08-11"}]
        rss = [{"video_id": "NORMAL", "channel": "A", "title": "본편",
                "description": "설명", "published": "2026-08-11"},
               {"video_id": "SHORTVID", "channel": "A", "title": "표식 없는 쇼츠",
                "description": "설명", "published": "2026-08-11"}]
        merged = {v["video_id"]: v for v in hist}
        merged.update({v["video_id"]: v for v in rss})
        for vid in [v for v in merged if v in fetch_history.short_ids()]:
            del merged[vid]

        out = []
        if "SHORTVID" in merged:
            out.append("  [길이로 판정한 쇼츠는 RSS 가 되살리면 안 됨] 후보에 남았습니다")
        if "NORMAL" not in merged:
            out.append("  [본편은 남아야 함] 멀쩡한 영상까지 걸러 냈습니다")
        elif merged["NORMAL"].get("description") != "설명":
            out.append("  [RSS 설명글은 계속 살려야 함] 설명이 사라졌습니다")
        return out
    finally:
        fetch_history.SHORT_IDS.clear()
        fetch_history.SHORT_IDS.update(saved)


# 실제 파이프라인 코드에 그 방어가 남아 있는가(주석만 남고 코드가 사라지는 것을 막는다)
def check_shorts_guard_wired() -> list[str]:
    import inspect
    import fetch_history
    import run_pipeline

    out = []
    if "SHORT_IDS.add" not in inspect.getsource(fetch_history):
        out.append("  [쇼츠 id 기록] fetch_history 가 더 이상 id 를 남기지 않습니다")
    if "short_ids()" not in inspect.getsource(run_pipeline.main):
        out.append("  [병합 뒤 재제거] run_pipeline 이 쇼츠를 다시 걷어 내지 않습니다")
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
    if wf.count("- cron:") < 4:
        out.append("  [예약을 넉넉히] GitHub 는 예약을 건너뛸 수 있어 4회 이상이어야 합니다")
    return out


def check_shorts() -> list[str]:
    out = []
    for dur, title, expect in SHORTS_CASES:
        got = is_short(dur, title, "")
        if got != expect:
            want = "쇼츠로" if expect else "본편으로"
            out.append(f"  [{want} 판정돼야 함] dur={dur} {title!r} → {got}")
    return out


def main() -> int:
    fails: list[str] = []
    for title, desc, expect in CASES:
        hits = match_candidate(title, desc)
        got = bool(hits)
        if got != expect:
            want = "잡혀야" if expect else "걸러져야"
            fails.append(f"  [{want} 함] {title[:46]!r} → hits={hits[:5]}")

    fails += check_shorts()
    fails += check_shorts_not_revived()
    fails += check_shorts_guard_wired()
    fails += check_names()
    fails += check_evidence()
    fails += check_model_errors()
    fails += check_unblock()
    fails += check_priority()
    fails += check_local_push()
    fails += check_handoff()
    fails += check_transient()
    fails += check_quota_parse()
    fails += check_model_order()
    fails += check_regen_guard()
    fails += check_stop_reason()
    fails += check_gh_fallback()
    fails += check_workflow_models_perm()
    fails += check_workflow_push_retry()
    total = (len(CASES) + len(SHORTS_CASES) + len(NAME_CASES)
             + len(EVIDENCE_CASES) + len(MODEL_ERR_CASES) + len(UNBLOCK_CASES)
             + 1     # 처리 우선순위
             + 4     # PC 자막 수집 git 처리
             + len(HANDOFF_CASES) + len(TRANSIENT_CASES) + 1 + 2 + 2 + 6 + 5 + 4)
    print(f"키워드·쇼츠·명칭·근거·모델·해제·우선순위·PC업로드·쿼터양보·보류판정·모델한도·안전장치·예비경로·쇼츠부활·푸시복구 — "
          f"{total - len(fails)}/{total} 통과")
    if fails:
        print("실패:", file=sys.stderr)
        for f in fails:
            print(f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
