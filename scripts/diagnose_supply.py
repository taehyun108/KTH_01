"""후보가 어디서 사라지는지 <단계별로> 센다 (Gemini 호출 없음).

왜 필요한가
  2026-08-16(일) 발행이 0건이었을 때, 나는 발행된 리포트의 요일 분포만 보고
  "채널들이 일요일에 덜 올린다"고 결론지었다. 틀린 방법이었다.
  발행량이 0인 이유는 <영상이 없어서>일 수도 있고 <우리가 떨어뜨려서>일 수도
  있는데, 결과만 봐서는 둘을 구분할 수 없다. 실제로 사용자가 그날 올라온
  슈카월드 영상을 바로 찾아냈고, 그 영상은 우리 데이터 어디에도 없었다
  — 발행도, 판정 기록(skipped.json)도 아니었다. 즉 후보에조차 오르지 못했고,
  그렇게 떨어진 것은 <아무 흔적도 남지 않는다>.

  이 스크립트는 그 흔적을 만든다. 각 단계에서 몇 건이 살아남는지 센다.

    ① 열거   — /videos 탭과 /streams 탭을 따로 센다
                (파이프라인은 /videos 만 본다. 라이브 다시보기는 /streams 에
                 있어서, 생방송이 주력인 채널은 통째로 안 보일 수 있다)
    ② 쇼츠   — 길이로 걸러 낸 수
    ③ 키워드 — 여기가 가장 의심스럽다. 열거 결과에는 설명글이 거의 없어서
                사실상 <제목만> 보고 판정한다. 공식 API 로 설명글을 채우는
                일은 이 필터를 <통과한 뒤>에나 일어나므로, 제목에 키워드가
                없는 영상은 설명글을 보기도 전에 사라진다.
    ④ 기판정 — 이미 발행했거나 skipped.json 에 있는 것

실행
    python scripts/diagnose_supply.py                 전 채널, 최근 14일
    python scripts/diagnose_supply.py --days 7
    python scripts/diagnose_supply.py --channel 슈카월드
    python scripts/diagnose_supply.py --video TgmE7y5syXk    이 영상만 추적
"""
from __future__ import annotations

import argparse
import collections
import sys
from datetime import date, timedelta

from config import CHANNELS, CHANNEL_LOOKBACK
from fetch_history import _entry_date, is_short
from fetch_rss import match_candidate, match_keywords

WD = "월화수목금토일"


def enumerate_tab(channel: dict[str, str], tab: str,
                  lookback: int) -> list[dict] | None:
    """채널의 한 탭을 열거한다. 탭이 없으면 None."""
    import yt_dlp

    cid = channel["channel_id"]
    url = f"https://www.youtube.com/channel/{cid}/{tab}"
    opts = {"extract_flat": "in_playlist", "playlistend": lookback,
            "quiet": True, "no_warnings": True, "skip_download": True,
            "ignoreerrors": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001
        print(f"    [{tab}] 열거 실패: {str(exc)[:90]}", file=sys.stderr)
        return None
    return [e for e in ((info or {}).get("entries") or []) if e and e.get("id")]


def trace_one(video_id: str) -> int:
    """영상 하나가 각 관문을 통과하는지 그대로 보여 준다."""
    import yt_meta

    yt_meta.announce()
    meta = yt_meta.fetch([video_id])
    if not meta or video_id not in meta:
        print(f"공식 API 로 {video_id} 를 찾지 못했습니다 "
              "(키가 없거나, 비공개·삭제된 영상입니다).", file=sys.stderr)
        return 1

    m = meta[video_id]
    title, desc, dur = m["title"], m["description"], m["duration"]
    print(f"\n영상 {video_id}")
    print(f"  제목   : {title}")
    print(f"  길이   : {dur}초" if dur is not None else "  길이   : 모름")
    print(f"  설명글 : {len(desc)}자")

    short = is_short(dur, title, desc)
    print(f"\n  ② 쇼츠 판정      : {'쇼츠 — 제외됨' if short else '본편 — 통과'}")

    # 파이프라인이 실제로 쓰는 두 경로를 나눠서 보여 준다.
    title_only = match_keywords(title)
    with_desc = match_candidate(title, desc)
    print(f"  ③ 키워드(제목만) : {'통과 ' + str(title_only[:6]) if title_only else '✗ 탈락'}"
          "   ← 열거 후보가 실제로 받는 판정")
    print(f"     키워드(설명글) : {'통과 ' + str(with_desc[:6]) if with_desc else '✗ 탈락'}"
          "   ← 설명글까지 봤다면")
    if not title_only and with_desc:
        print("     ‼ 설명글을 먼저 채웠다면 살았을 후보입니다 "
              "— 지금은 키워드 필터가 설명글보다 먼저 돕니다.")

    import seen_store
    from build_index import load_existing
    published = {r.get("video_id") for r in load_existing()}
    store = seen_store.load()
    if video_id in published:
        print("  ④ 기판정         : 이미 발행됨")
    elif video_id in store:
        e = store[video_id]
        print(f"  ④ 기판정         : {e['reason']} ({e['date']} 기록)")
    else:
        print("  ④ 기판정         : 기록 없음")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--channel", default="")
    ap.add_argument("--video", default="")
    args = ap.parse_args()

    if args.video:
        return trace_one(args.video)

    chans = [c for c in CHANNELS
             if not args.channel or args.channel in c["name"]]
    if not chans:
        print(f"'{args.channel}' 채널을 찾지 못했습니다.", file=sys.stderr)
        return 1

    cutoff = (date.today() - timedelta(days=args.days)).isoformat()
    # 요일별 집계 — '일요일엔 영상이 없다'가 사실인지 확인하려는 것이 핵심이다.
    by_wd_seen: collections.Counter = collections.Counter()
    by_wd_pass: collections.Counter = collections.Counter()
    totals = collections.Counter()

    print(f"후보 공급 진단 — 최근 {args.days}일 (기준 {cutoff}), 채널 {len(chans)}개\n")
    for ch in chans:
        print(f"■ {ch['name']}")
        rows = []
        for tab in ("videos", "streams"):
            entries = enumerate_tab(ch, tab, CHANNEL_LOOKBACK)
            if entries is None:
                continue
            recent = [e for e in entries if _entry_date(e) >= cutoff]
            print(f"    [{tab:>7}] 열거 {len(entries)}건 · 최근 {args.days}일 {len(recent)}건")
            totals[f"열거:{tab}"] += len(recent)
            for e in recent:
                rows.append((tab, e))

        for tab, e in rows:
            d = _entry_date(e)
            title = e.get("title") or ""
            desc = (e.get("description") or "").strip()
            if is_short(e.get("duration"), title, desc):
                totals["쇼츠 제외"] += 1
                continue
            totals["본편"] += 1
            wd = WD[date.fromisoformat(d).weekday()] if d else "?"
            by_wd_seen[wd] += 1
            if match_keywords(f"{title} {desc}"):
                totals["키워드 통과"] += 1
                by_wd_pass[wd] += 1
            else:
                totals["키워드 탈락"] += 1
                if tab == "streams" or wd in "토일":
                    # 주말·라이브가 통째로 사라지는지가 이번 조사의 핵심이다.
                    print(f"      ✗ {d}({wd}) [{tab}] {title[:56]}")
        print()

    print("── 단계별 합계 " + "─" * 40)
    for k in ("열거:videos", "열거:streams", "쇼츠 제외", "본편",
              "키워드 통과", "키워드 탈락"):
        print(f"  {k:<14} {totals[k]:>4}건")

    print("\n── 요일별 (쇼츠 제외 본편 기준) " + "─" * 24)
    print(f"  {'요일':<6}{'올라온 영상':>10}{'키워드 통과':>12}")
    for wd in WD:
        if by_wd_seen[wd] or by_wd_pass[wd]:
            print(f"  {wd:<6}{by_wd_seen[wd]:>10}{by_wd_pass[wd]:>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
