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

# 윈도우 한글 콘솔은 기본 코드페이지가 cp949 라, '✔' 같은 문자를 출력하는 순간
# UnicodeEncodeError 로 스크립트가 통째로 죽는다. 출력만 UTF-8 로 바꿔 둔다.
# (errors='replace' 라 혹시 표현 못 하는 글자가 있어도 멈추지 않는다)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

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


def _current_branch() -> str:
    code, out = _git("rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 and out and out != "HEAD" else "main"


def _sync_and_push(branch: str, tries: int = 3) -> tuple[bool, str]:
    """원격 변경을 먼저 받아 붙인 뒤 push 한다.

    ※ 이게 없으면 첫 실행부터 반드시 실패한다.
      Actions 가 하루 두 번 main 에 리포트를 커밋하므로 PC 클론은 거의 항상
      뒤처져 있고, 그 상태로 push 하면 'fetch first' 로 거부당한다.
      실제로 재현해 확인한 문제다.

    자막 캐시는 cache/transcripts/<id>.json 로 파일이 서로 겹치지 않아
    리베이스 충돌이 사실상 없다. 그래도 충돌하면 깨끗이 되돌리고 알린다.

    push 직전에 봇이 또 올릴 수 있으므로 몇 번 다시 시도한다.
    """
    last = ""
    for attempt in range(1, tries + 1):
        code, out = _git("fetch", "origin", branch)
        if code != 0:
            last = f"git fetch 실패:\n{out}"
            time.sleep(2 * attempt)
            continue

        # --autostash: 저장소에 손대 둔 것이 남아 있어도 리베이스가 거부되지 않게
        # 잠시 치웠다가 되돌려 놓는다. 이것이 없으면 'cannot rebase: You have
        # unstaged changes' 로 막힌다(모의 실행에서 실제로 재현됨).
        code, out = _git("rebase", "--autostash", f"origin/{branch}")
        if code != 0:
            _git("rebase", "--abort")
            return False, ("원격 변경과 충돌해 자동으로 합치지 못했습니다.\n"
                           "저장소 폴더에서 아래를 실행한 뒤 다시 시도해 주세요.\n"
                           "    git pull --rebase\n"
                           f"(git 메시지: {out.splitlines()[0] if out else ''})")

        code, out = _git("push", "-u", "origin", branch)
        if code == 0:
            return True, ""
        last = out
        print(f"  push 재시도 {attempt}/{tries} — 원격이 그새 또 바뀐 듯합니다.",
              file=sys.stderr)
        time.sleep(2 * attempt)
    return False, f"git push 실패:\n{last}"


def _check_env() -> list[str]:
    """실행 전에 빠진 준비물을 한 번에 알려 준다.

    처음 돌릴 때 라이브러리 하나가 없어서 낯선 ImportError 만 보고 막히는 일이
    없도록, 무엇이 없는지 사람 말로 먼저 알려 준다.
    """
    problems = []
    for mod, why in (("youtube_transcript_api", "자막 받기"),
                     ("yt_dlp", "자막 대체 경로·채널 목록"),
                     ("feedparser", "RSS 수집")):
        try:
            __import__(mod)
        except ImportError:
            problems.append(f"  · {mod} 가 설치돼 있지 않습니다 ({why}에 필요).")
    code, _ = _git("rev-parse", "--git-dir")
    if code != 0:
        problems.append("  · 이 폴더가 git 저장소가 아닙니다. "
                        "git clone 으로 받은 폴더에서 실행해 주세요.")
    if problems:
        problems.append("\n해결: 저장소 폴더에서  pip install -r requirements.txt")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="유튜브 자막을 받아 캐시에 넣습니다.")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="이번에 받을 최대 건수")
    ap.add_argument("--no-push", action="store_true", help="커밋·푸시하지 않음")
    ap.add_argument("--dry-run", action="store_true", help="받지 않고 대상만 출력")
    args = ap.parse_args()

    if problems := _check_env():
        print("실행에 필요한 준비물이 빠져 있습니다:\n" + "\n".join(problems), file=sys.stderr)
        return 1

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

            # 예외 없이 빈/짧은 결과가 오는 경우도 있다(자막 트랙은 있는데 내용이 없는 등).
            # 예전에는 예외일 때만 폴백해서, 이런 영상은 폴백을 시도조차 못 하고 버려졌다.
            if len(text) <= transcript_cache.MIN_CHARS:
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

    branch = _current_branch()

    _, dirty = _git("status", "--porcelain", "cache/")
    if dirty:
        for cmd in (("add", "cache/"),
                    ("commit", "-m", f"chore: 자막 캐시 갱신 ({n}건)")):
            code, out = _git(*cmd)
            if code != 0:
                print(f"git {' '.join(cmd)} 실패:\n{out}", file=sys.stderr)
                return 1

    # 새 변경이 없어도, <아직 못 올린 커밋>이 남아 있으면 올려야 한다.
    #   지난 실행이 커밋까지는 했는데 push 에서 막힌 경우(원격이 앞서 있었다 등),
    #   다음 실행은 '바뀐 게 없다'며 그대로 끝나 자막이 PC 에만 영영 남았다.
    #   모의 실행에서 실제로 재현된 문제다.
    _git("fetch", "origin", branch)
    _, ahead = _git("rev-list", "--count", f"origin/{branch}..HEAD")
    n_ahead = int(ahead) if ahead.isdigit() else 0
    if not dirty and n_ahead == 0:
        print("올릴 변경이 없습니다.")
        return 0
    if not dirty:
        print(f"새로 받은 자막은 없지만 아직 못 올린 커밋 {n_ahead}건이 있어 올립니다.")

    pushed, err = _sync_and_push(branch)
    if not pushed:
        print(err, file=sys.stderr)
        print("\n자막은 이 PC 에 정상으로 저장돼 있습니다. 위 문제만 해결하고 다시 실행하면\n"
              "이미 받은 자막은 다시 받지 않고 올리기만 합니다.", file=sys.stderr)
        return 1
    print(f"저장소({branch})에 올렸습니다. 다음 자동 실행부터 이 자막이 쓰입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
