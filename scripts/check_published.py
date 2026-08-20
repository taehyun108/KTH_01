"""이미 발행된 리포트 중에 쇼츠가 섞여 있는지 <공식 API 로> 확인한다.

왜 필요한가
  쇼츠 제외 장치는 여러 겹으로 깔아 뒀다.
    · yt-dlp 열거에서 길이로 거르고(fetch_history)
    · RSS 병합이 되살린 것을 다시 걷어 내고(run_pipeline)
    · 공식 API 로 길이를 확보해 한 번 더 거른다(yt_meta.enrich)
  그런데 이 셋은 전부 <발행 전> 장치다. 하나라도 새면 그대로 나간다.
  실제로 2026-08-11 에 한 건이 새어 발행됐고, 사람이 눈으로 보고서야 알았다.

  이 스크립트는 <발행된 결과물>을 뒤에서 검사한다.
  앞의 장치가 왜 실패했는지와 무관하게, 결과에 쇼츠가 있으면 잡아낸다.

  ※ 길이를 모르는 영상은 실패로 치지 않는다. 키가 없거나 조회에 실패했을 때
    멀쩡한 실행을 빨갛게 만들면, 정작 진짜 쇼츠가 섞였을 때 묻힌다.

  실행: python scripts/check_published.py            (쇼츠가 있으면 실패)
        python scripts/check_published.py --list     (전부 길이와 함께 나열)
"""
from __future__ import annotations

import json
import sys

from config import REPORTS_JSON
from fetch_history import is_short


def published() -> list[dict]:
    data = json.loads(REPORTS_JSON.read_text(encoding="utf-8"))
    return data.get("reports", []) if isinstance(data, dict) else data


def main() -> int:
    show_all = "--list" in sys.argv
    import yt_meta

    reports = published()
    ids = [r["video_id"] for r in reports if r.get("video_id")]
    if not ids:
        print("발행된 리포트에 video_id 가 없습니다 — 검사할 것이 없습니다.")
        return 0

    yt_meta.announce()
    if not yt_meta.available():
        print("YOUTUBE_API_KEY 가 없어 길이를 확인할 수 없습니다 — 검사를 건너뜁니다.",
              file=sys.stderr)
        return 0

    print(f"발행물 쇼츠 검사 — {len(ids)}건 조회")
    meta = yt_meta.fetch(ids)
    if not meta:
        print("조회에 실패했습니다 — 검사를 건너뜁니다.", file=sys.stderr)
        return 0

    by_id = {r["video_id"]: r for r in reports if r.get("video_id")}
    bad, unknown, ok = [], [], 0
    for vid, m in meta.items():
        r = by_id.get(vid)
        if not r:
            continue
        dur = m.get("duration")
        if dur is None or dur <= 0:
            unknown.append((vid, r))
            continue
        if is_short(dur, r.get("title", ""), m.get("description", "")):
            bad.append((vid, r, dur))
        else:
            ok += 1
        if show_all:
            print(f"  {dur:>6}초  {r.get('date','')}  {r.get('title','')[:44]}")

    missing = len(ids) - len(meta)
    print(f"  본편 {ok}건 · 길이 미상 {len(unknown)}건"
          + (f" · 조회 안 됨 {missing}건" if missing else ""))

    if not bad:
        print("통과 — 발행물에 쇼츠 없음")
        return 0

    print(f"\n‼ 발행물에 쇼츠가 {len(bad)}건 섞여 있습니다:", file=sys.stderr)
    for vid, r, dur in bad:
        print(f"  {dur}초 · {r.get('date','')} · {r.get('title','')[:50]}\n"
              f"      https://www.youtube.com/watch?v={vid}\n"
              f"      site/news/{r.get('id','')}.html", file=sys.stderr)
    print("\n  scripts/delete_report.py 로 지우고, 어느 관문이 샜는지 확인하세요.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
