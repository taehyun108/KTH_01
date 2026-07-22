"""
기존 reports.json 의 category 를 키워드 휴리스틱으로 재보정한다.
(정책 vs 시황, 글로벌 vs 국내) — Gemini 분류 개선 이전 리포트 교정용. API 불필요.

실행: python scripts/reclassify.py
"""
from __future__ import annotations

import json

from config import REPORTS_JSON

# 핵심 '트리거'가 정책/제도/규제/지정학이면 policy 로 본다 (제목 기준)
POLICY_TRIGGERS = [
    "관세", "수출규제", "수출통제", "무역분쟁", "반덤핑", "제재",
    "금리", "연준", "한국은행", "한은", "FOMC", "통화정책", "기준금리",
    "보조금", "IRA", "45X", "규제", "인허가", "안전기준", "환경규제",
    "지정학", "선거", "시위", "정책", "중동", "전력망 정책",
]
# 주된 무대가 한국임을 나타내는 단서 (제목+요약 기준)
KOREA_CUES = ["코스피", "코스닥", "한국", "국내", "현대차", "기아", "한은", "한국은행", "원화"]


def classify(title: str, summary: str) -> str:
    is_policy = any(k in (title or "") for k in POLICY_TRIGGERS)
    is_korea = any(k in f"{title} {summary}" for k in KOREA_CUES)
    return f"{'korea' if is_korea else 'global'}-{'policy' if is_policy else 'market'}"


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
