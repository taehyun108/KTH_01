"""
3단계: /site/data/reports.json 인덱스 갱신.

신규 리포트 메타 리스트를 기존 reports.json 에 병합(중복 id 는 갱신)하고
최신순으로 정렬해 다시 기록한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config import REPORTS_JSON, DATA_DIR, NEWS_DIR, MAX_REPORTS


def load_existing() -> list[dict[str, Any]]:
    if REPORTS_JSON.exists():
        return json.loads(REPORTS_JSON.read_text(encoding="utf-8")).get("reports", [])
    return []


def merge(new_reports: list[dict[str, Any]]) -> None:
    by_id = {r["id"]: r for r in load_existing()}
    for r in new_reports:
        by_id[r["id"]] = r
    reports = sorted(by_id.values(), key=lambda r: r["date"], reverse=True)  # 최신순

    # 보관 상한: 최신 MAX_REPORTS 건만 유지, 초과분 HTML 은 삭제
    if len(reports) > MAX_REPORTS:
        for r in reports[MAX_REPORTS:]:
            f = NEWS_DIR / r.get("url", "")
            if r.get("url") and f.exists():
                f.unlink()
        reports = reports[:MAX_REPORTS]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_JSON.write_text(
        json.dumps(
            {"generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "reports": reports},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"reports.json 갱신 완료 — 총 {len(reports)}건")


if __name__ == "__main__":
    merge([])  # 정렬/타임스탬프만 갱신
