"""리포트 아카이브(site/data/reports.json + site/news/*.html)를 읽고 쓰는 단 하나의 입구.

예전에는 build_index(병합)·delete_report(삭제)·check_published(쇼츠 제거)가 같은 JSON 을
각자 읽어 각자 형식으로 썼다. merge 는 삭제를 못 해서 delete_report 가 generated_at·channels 를
똑같이 손으로 적었고, 한 곳은 들여쓰기가 달랐다. 쓰는 곳이 하나면 형식·분류 보정·파일 정리·
원자적 교체를 한 번만 두면 된다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Callable, Iterable

from config import (REPORTS_JSON, DATA_DIR, NEWS_DIR, MAX_REPORTS, CHANNELS,
                    normalize_category, normalize_relation)


def load() -> list[dict[str, Any]]:
    if REPORTS_JSON.exists():
        return json.loads(REPORTS_JSON.read_text(encoding="utf-8")).get("reports", [])
    return []


def save(reports: list[dict[str, Any]]) -> None:
    """인덱스를 기록한다. 임시 파일에 쓴 뒤 교체해 쓰다 끊겨도 반쪽 파일이 남지 않는다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "channels": [c["name"] for c in CHANNELS],  # 설정된 전체 채널(0건 포함 표시용)
            "reports": reports,
        },
        ensure_ascii=False, indent=2,
    )
    tmp = REPORTS_JSON.with_name(REPORTS_JSON.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, REPORTS_JSON)


def _fix_classification(reports: list[dict[str, Any]]) -> None:
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


def _delete_html(r: dict[str, Any]) -> None:
    name = r.get("url") or (f"{r.get('id', '')}.html" if r.get("id") else "")
    if name:
        f = NEWS_DIR / name
        if f.exists():
            f.unlink()


def merge(new_reports: list[dict[str, Any]]) -> None:
    """신규 리포트를 병합(중복 id 는 갱신)하고 최신순으로 정렬해 기록한다."""
    by_id = {r["id"]: r for r in load()}
    for r in new_reports:
        by_id[r["id"]] = r
    reports = sorted(by_id.values(), key=lambda r: r["date"], reverse=True)  # 최신순
    _fix_classification(reports)

    # 보관 상한: 최신 MAX_REPORTS 건만 유지, 초과분 HTML 은 삭제 (None = 무제한)
    if MAX_REPORTS is not None and len(reports) > MAX_REPORTS:
        for r in reports[MAX_REPORTS:]:
            _delete_html(r)
        reports = reports[:MAX_REPORTS]

    save(reports)
    print(f"reports.json 갱신 완료 — 총 {len(reports)}건")


def remove(match: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
    """조건에 맞는 리포트를 인덱스와 HTML 에서 함께 지운다. 지운 항목을 돌려준다."""
    reports = load()
    gone = [r for r in reports if match(r)]
    if not gone:
        return []
    for r in gone:
        _delete_html(r)
    save([r for r in reports if not match(r)])
    return gone


def remove_ids(ids: Iterable[str]) -> list[dict[str, Any]]:
    want = set(ids)
    return remove(lambda r: r.get("id") in want)


def remove_video_ids(video_ids: Iterable[str]) -> list[dict[str, Any]]:
    want = set(video_ids)
    return remove(lambda r: r.get("video_id") in want)
