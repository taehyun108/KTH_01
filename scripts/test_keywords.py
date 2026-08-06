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
    total = len(CASES) + len(SHORTS_CASES)
    print(f"키워드·쇼츠 판정 테스트 — {total - len(fails)}/{total} 통과")
    if fails:
        print("실패:", file=sys.stderr)
        for f in fails:
            print(f, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
