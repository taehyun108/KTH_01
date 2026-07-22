"""
파이프라인 오케스트레이터 — GitHub Actions 에서 하루 1~2회 실행.

  RSS 수집 → 1차 키워드 필터 → 자막 추출 → Claude 2차 판단·구조화 → HTML 생성
  → reports.json 인덱스 갱신

무관/애매한 건은 /drafts 로 보내 수동 확인.
"""
from __future__ import annotations

import os
import sys

from fetch_rss import collect_candidates
from generate_report import process_video
from build_index import merge


def main() -> int:
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 미설정 — 리포트 생성 단계를 건너뜁니다.", file=sys.stderr)
        return 0

    candidates = collect_candidates()
    print(f"1차 후보 {len(candidates)}건")

    new_reports = []
    for meta in candidates:
        try:
            result = process_video(meta)
            if result:
                print(f"  ✔ 생성: {result['id']}")
                new_reports.append(result)
            else:
                print(f"  – drafts: {meta['title'][:30]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 실패 {meta.get('video_id')}: {exc}", file=sys.stderr)

    if new_reports:
        merge(new_reports)
    print(f"완료 — 신규 리포트 {len(new_reports)}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
