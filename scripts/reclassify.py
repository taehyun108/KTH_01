"""
기존 reports.json 의 category 를 키워드 휴리스틱으로 재보정한다.
분류: 거시경제(macro) / 정책·시사(policy) / 산업·시황(market) × (글로벌·국내).
Gemini 분류 개선 이전 리포트 교정용. API 불필요.

실행: python scripts/reclassify.py
"""
from __future__ import annotations

import json

from config import REPORTS_JSON

# 1) 거시경제: 금리·환율·유가·증시 전반·통화정책 등 거시 지표/시장 흐름 (제목 기준, 최우선)
MACRO_TERMS = [
    "금리", "환율", "유가", "인플레", "물가", "거시", "매크로", "증시", "코스피", "코스닥",
    "뉴욕증시", "나스닥", "s&p", "FOMC", "연준", "한국은행", "한은", "통화정책", "기준금리",
    "경기", "경제지표", "고용지표", "GDP", "국채", "달러",
]
# 2) 정책·시사: 제도·규제·외교 (금리/통화정책 제외 — 그건 macro)
POLICY_TRIGGERS = [
    "관세", "수출규제", "수출통제", "무역분쟁", "반덤핑", "제재",
    "보조금", "IRA", "45X", "규제", "인허가", "안전기준", "환경규제",
    "지정학", "선거", "시위", "정책",
]
# 주된 무대가 한국임을 나타내는 단서 (정책/시황의 글로벌·국내 구분용)
KOREA_CUES = ["코스피", "코스닥", "한국", "국내", "현대차", "기아", "한은", "한국은행", "원화"]


def classify(title: str, summary: str) -> str:
    t = title or ""
    if any(k in t for k in POLICY_TRIGGERS):          # 관세·규제·지정학 → 정책
        region = "korea" if any(k in f"{title} {summary}" for k in KOREA_CUES) else "global"
        return f"{region}-policy"
    if any(k in t for k in MACRO_TERMS):              # 금리·환율·증시 → 거시경제
        return "macro"
    region = "korea" if any(k in f"{title} {summary}" for k in KOREA_CUES) else "global"
    return f"{region}-market"                          # 실적·수급·투자 → 시황


def main() -> None:
    d = json.loads(REPORTS_JSON.read_text(encoding="utf-8"))
    changed = 0
    for r in d["reports"]:
        new = classify(r.get("title", ""), r.get("summary", ""))
        if new != r.get("category"):
            print(f"  {r.get('category',''):14} -> {new:14} | {r['title'][:42]}")
            r["category"] = new
            changed += 1
    REPORTS_JSON.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"재분류 {changed}건 / 총 {len(d['reports'])}건")


if __name__ == "__main__":
    main()
