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
        python scripts/check_published.py --fix      (찾으면 지우고 영구 차단)
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
    fix = "--fix" in sys.argv
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

    if not fix:
        print("\n  --fix 를 붙이면 지우고 영구 차단합니다.", file=sys.stderr)
        return 1
    return _remove(bad, reports)


def _remove(bad: list, reports: list[dict]) -> int:
    """쇼츠 리포트를 지우고, 다시는 후보가 되지 않게 영구 기록한다.

    ※ 왜 실패로 끝내지 않고 <스스로 치우는가>
      커밋 단계가 if: always() 라, 여기서 실패만 시켜서는 그 커밋을 못 막는다.
      막으려고 커밋 조건을 손대면 이번엔 <다른 이유로 실패한 실행>이 만든
      멀쩡한 리포트까지 함께 버려진다. 그래서 막는 대신 치운다.
      사람이 눈으로 보고 신고할 때까지 남아 있는 것이 가장 나쁘다.
    """
    from config import NEWS_DIR
    import seen_store

    data = json.loads(REPORTS_JSON.read_text(encoding="utf-8"))
    drop = {vid for vid, _, _ in bad}
    kept = [r for r in data.get("reports", []) if r.get("video_id") not in drop]
    data["reports"] = kept

    store = seen_store.load()
    for vid, r, dur in bad:
        f = NEWS_DIR / f"{r.get('id','')}.html"
        if f.exists():
            f.unlink()
        # 영구 차단 — 쇼츠는 영상의 성질이라 나중에 뒤집힐 판단이 아니다
        seen_store.record(store, vid, seen_store.REASON_SHORTS, r.get("title", ""))
    seen_store.save(store)
    REPORTS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(f"\n  → {len(bad)}건을 지우고 영구 차단했습니다 (남은 리포트 {len(kept)}건).")
    print("  앞 관문이 왜 샜는지는 따로 확인해야 합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
