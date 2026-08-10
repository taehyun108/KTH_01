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
    fails += check_names()
    fails += check_evidence()
    fails += check_model_errors()
    fails += check_unblock()
    fails += check_priority()
    fails += check_local_push()
    fails += check_handoff()
    total = (len(CASES) + len(SHORTS_CASES) + len(NAME_CASES)
             + len(EVIDENCE_CASES) + len(MODEL_ERR_CASES) + len(UNBLOCK_CASES)
             + 1     # 처리 우선순위
             + 4     # PC 자막 수집 git 처리
             + len(HANDOFF_CASES))
    print(f"키워드·쇼츠·명칭·근거·모델·해제·우선순위·PC업로드·쿼터양보 — "
          f"{total - len(fails)}/{total} 통과")
    if fails:
        print("실패:", file=sys.stderr)
        for f in fails:
            print(f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
