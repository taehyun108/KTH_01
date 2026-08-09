"""집 PC 에서 실행 — 유튜브 자막을 받아 저장소에 올린다.

배경
  GitHub Actions 러너 IP 는 유튜브가 차단해 자막을 한 건도 못 가져옵니다
  (RequestBlocked). 가정용 인터넷은 막히지 않으므로, '자막 받기'만 PC 가 맡고
  요약은 그대로 Actions 가 합니다.

  이 스크립트는 Gemini API 키가 필요 없습니다. 키는 계속 Actions 시크릿에만
  두시면 됩니다. PC 가 하는 일은 자막을 받아 cache/transcripts 에 넣고
  git push 하는 것까지입니다.

실행
    python scripts/fetch_transcripts_local.py              # 받고 커밋·푸시까지
    python scripts/fetch_transcripts_local.py --no-push    # 받기만 (확인용)
    python scripts/fetch_transcripts_local.py --limit 30   # 이번엔 30건만
    python scripts/fetch_transcripts_local.py --dry-run    # 뭘 받을지 목록만

PC 가 꺼져 있어도 파이프라인은 지금과 똑같이 돕니다(캐시가 없을 뿐입니다).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import date, timedelta

import transcript_cache
from config import MAX_AGE_DAYS, ROOT

# 유튜브에 너무 빠르게 연달아 요청하면 가정용 IP 도 일시 차단될 수 있다.
SLEEP_SEC = 1.5
# 한 번에 받을 최대 건수 기본값 (오래 걸리지 않게)
DEFAULT_LIMIT = 60


def _candidates() -> list[dict]:
    """파이프라인과 같은 방식으로 후보를 모은다(같은 영상을 보도록)."""
    from fetch_history import collect_history
    from fetch_rss import collect_candidates

    rss = collect_candidates()
    cutoff = (date.today() - timedelta(days=MAX_AGE_DAYS)).isoformat()
    hist = collect_history(cutoff)
    merged = {v["video_id"]: v for v in hist}
    merged.update({v["video_id"]: v for v in rss})
    return sorted(merged.values(), key=lambda v: v.get("published", ""), reverse=True)


def _already_published() -> set[str]:
    from run_pipeline import _seen_video_ids
    return _seen_video_ids()


def _git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="유튜브 자막을 받아 캐시에 넣습니다.")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="이번에 받을 최대 건수")
    ap.add_argument("--no-push", action="store_true", help="커밋·푸시하지 않음")
    ap.add_argument("--dry-run", action="store_true", help="받지 않고 대상만 출력")
    args = ap.parse_args()

    print("후보를 모으는 중입니다…")
    cands = _candidates()
    published = _already_published()

    todo = [c for c in cands
            if c["video_id"] not in published and not transcript_cache.has(c["video_id"])]
    n_have, _ = transcript_cache.stats()
    print(f"후보 {len(cands)}건 · 이미 발행 {len(published)}건 · 캐시 보유 {n_have}건 "
          f"→ 받을 대상 {len(todo)}건")

    if args.dry_run:
        for c in todo[:args.limit]:
            print(f"  {c['video_id']}  {c['title'][:60]}")
        return 0

    todo = todo[:args.limit]
    if not todo:
        print("새로 받을 자막이 없습니다.")
    else:
        # 여기서 임포트해야 Gemini 관련 모듈을 건드리지 않는다(PC 에 API 키 불필요)
        from generate_report import _transcript_api, _ytdlp_transcript

        ok = fail = 0
        for i, c in enumerate(todo, 1):
            vid, title = c["video_id"], c.get("title", "")
            text, source = "", ""
            try:
                text = _transcript_api(vid)
                source = "youtube-transcript-api"
            except Exception as exc:  # noqa: BLE001
                brief = " ".join(str(exc).split())[:80]
                print(f"  [{i}/{len(todo)}] {vid}: transcript-api 실패 — {brief}")
                text, source = _ytdlp_transcript(vid)
                if source == "unavailable":
                    text = ""

            if text and transcript_cache.put(vid, text, source or "local", title):
                ok += 1
                print(f"  [{i}/{len(todo)}] ✔ {vid} {len(text):>6}자  {title[:44]}")
            else:
                fail += 1
                print(f"  [{i}/{len(todo)}] – {vid} 자막 없음  {title[:44]}")
            time.sleep(SLEEP_SEC)

        print(f"\n완료 — 성공 {ok}건 · 실패 {fail}건")
        if ok == 0 and fail > 0:
            print("전부 실패했습니다. 이 PC 에서도 유튜브 자막이 막혔을 수 있습니다.\n"
                  "브라우저로 아무 영상이나 자막이 보이는지 먼저 확인해 보십시오.",
                  file=sys.stderr)

    removed = transcript_cache.prune()
    if removed:
        print(f"오래된 캐시 {removed}건 정리")

    n, chars = transcript_cache.stats()
    print(f"캐시 현황 — {n}건 · 약 {chars:,}자")

    if args.no_push:
        print("(--no-push 이므로 커밋하지 않습니다)")
        return 0

    code, out = _git("status", "--porcelain", "cache/")
    if not out:
        print("올릴 변경이 없습니다.")
        return 0

    for cmd in (("add", "cache/"),
                ("commit", "-m", f"chore: 자막 캐시 갱신 ({n}건)"),
                ("push",)):
        code, out = _git(*cmd)
        if code != 0:
            print(f"git {' '.join(cmd)} 실패:\n{out}", file=sys.stderr)
            return 1
    print("저장소에 올렸습니다. 다음 자동 실행부터 이 자막이 쓰입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
