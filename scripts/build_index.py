"""
3단계: /site/data/reports.json 인덱스 갱신.

신규 리포트 메타 리스트를 기존 reports.json 에 병합(중복 id 는 갱신)하고
최신순으로 정렬해 다시 기록한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config import (REPORTS_JSON, DATA_DIR, NEWS_DIR, MAX_REPORTS, CHANNELS,
                    normalize_category, normalize_relation)


def load_existing() -> list[dict[str, Any]]:
    if REPORTS_JSON.exists():
        return json.loads(REPORTS_JSON.read_text(encoding="utf-8")).get("reports", [])
    return []


def merge(new_reports: list[dict[str, Any]]) -> None:
    by_id = {r["id"]: r for r in load_existing()}
    for r in new_reports:
        by_id[r["id"]] = r
    reports = sorted(by_id.values(), key=lambda r: r["date"], reverse=True)  # 최신순

    # 목록 화면은 등록된 카테고리만 칩으로 그린다. 목록에 없는 값이 하나라도 있으면
    # 그 리포트는 어느 칩에도 안 잡혀 '전체 367 / 칩 합계 365' 처럼 조용히 어긋난다.
    # 생성 단계에서도 막지만, 지난 데이터까지 훑는 이 자리에서 한 번 더 고정한다.
    fixed = 0
    for r in reports:
        cat, cat_ok = normalize_category(r.get("category"))
        rel, rel_ok = normalize_relation(r.get("relation"))
        if not cat_ok:
            print(f"  [분류] {r['id']}: category {r.get('category')!r} → {cat!r}")
            r["category"] = cat
            fixed += 1
        if not rel_ok:
            print(f"  [분류] {r['id']}: relation {r.get('relation')!r} → {rel!r}")
            r["relation"] = rel
            fixed += 1
    if fixed:
        print(f"  [분류] 등록되지 않은 값 {fixed}건을 교정했습니다")

    # 보관 상한: 최신 MAX_REPORTS 건만 유지, 초과분 HTML 은 삭제 (None = 무제한)
    if MAX_REPORTS is not None and len(reports) > MAX_REPORTS:
        for r in reports[MAX_REPORTS:]:
            f = NEWS_DIR / r.get("url", "")
            if r.get("url") and f.exists():
                f.unlink()
        reports = reports[:MAX_REPORTS]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "channels": [c["name"] for c in CHANNELS],  # 설정된 전체 채널(0건 포함 표시용)
                "reports": reports,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"reports.json 갱신 완료 — 총 {len(reports)}건")


if __name__ == "__main__":
    merge([])  # 정렬/타임스탬프만 갱신
