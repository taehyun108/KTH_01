"""
파이프라인 오케스트레이터 — GitHub Actions 에서 하루 1~2회 실행.

  RSS 수집 → 1차 키워드 필터 → 자막 추출 → Claude 2차 판단·구조화 → HTML 생성
  → reports.json 인덱스 갱신

무관/애매한 건은 /drafts 로 보내 수동 확인.
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict

from fetch_rss import collect_candidates
from generate_report import process_video
from build_index import merge, load_existing
from config import MAX_CANDIDATES_PER_RUN


def _extract_video_id(url: str) -> str | None:
    """watch?v=ID · shorts/ID · youtu.be/ID · embed/ID 모두에서 영상 id 추출."""
    for pat in (r"[?&]v=([\w-]{6,})", r"/shorts/([\w-]{6,})",
                r"youtu\.be/([\w-]{6,})", r"/embed/([\w-]{6,})"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    return None


def _seen_video_ids() -> set[str]:
    """이미 리포트가 만들어진 영상 id (중복 생성 방지). video_id 필드 우선, 없으면 URL 파싱."""
    seen = set()
    for r in load_existing():
        vid = r.get("video_id") or _extract_video_id(r.get("video", ""))
        if vid:
            seen.add(vid)
    return seen


def main() -> int:
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 미설정 — 리포트 생성 단계를 건너뜁니다.", file=sys.stderr)
        return 0

    candidates = collect_candidates()
    seen = _seen_video_ids()
    fresh = [c for c in candidates if c["video_id"] not in seen]

    # 채널별로 묶어 각 채널 내 최신순 정렬
    by_ch: dict[str, list] = defaultdict(list)
    for c in fresh:
        by_ch[c["channel"]].append(c)
    for lst in by_ch.values():
        lst.sort(key=lambda c: c.get("published", ""), reverse=True)

    # 라운드로빈: 채널을 번갈아 뽑아 특정 채널 독점 방지 (슈카월드 등 공정 포함)
    selected: list = []
    while len(selected) < MAX_CANDIDATES_PER_RUN and any(by_ch.values()):
        for ch in list(by_ch):
            if by_ch[ch]:
                selected.append(by_ch[ch].pop(0))
                if len(selected) >= MAX_CANDIDATES_PER_RUN:
                    break
    fresh = selected

    dist = ", ".join(f"{k} {sum(1 for c in fresh if c['channel'] == k)}"
                     for k in dict.fromkeys(c["channel"] for c in fresh))
    print(f"1차 후보 {len(candidates)}건 · 신규 {len(fresh)}건 처리 (상한 {MAX_CANDIDATES_PER_RUN})")
    print(f"  처리 분배: {dist or '없음'}")

    new_reports = []
    for meta in fresh:
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
