"""설정된 채널이 실제로 살아 있는지 확인한다 (Gemini 호출 없음·빠름).

왜 필요한가
  채널을 추가할 때 넣는 것은 사람이 읽을 수 없는 24자짜리 id(UC…) 다.
  한 글자만 틀려도 오류가 나지 않고 <조용히 0건>이 될 뿐이라, 몇 주 뒤에야
  "저 채널은 왜 하나도 안 올라오지?" 하고 알아차리게 된다.
  그래서 각 채널의 RSS 가 응답하는지, 채널이 밝히는 이름이 우리가 적은 이름과
  맞는지 확인한다.

  RSS 는 자막과 달리 Actions 러너에서도 정상 응답하므로 CI 에서 돌릴 수 있다.
  가져오기는 파이프라인이 쓰는 fetch_rss 의 함수를 그대로 써서, 헤더·재시도
  동작까지 실제와 같은 경로로 확인한다.

실행
    python scripts/check_channels.py          검사 (문제가 있으면 실패)
    python scripts/check_channels.py --warn   문제가 있어도 실패시키지 않음
"""
from __future__ import annotations

import sys

from config import CHANNELS
from fetch_rss import RSS_URL, _fetch_rss_bytes


def probe(channel: dict[str, str]) -> tuple[str, int, str]:
    """(상태, 영상 수, 채널이 밝히는 이름)."""
    import feedparser

    cid = channel.get("channel_id", "")
    if not cid or cid.startswith("TODO"):
        return "채널 id 미설정", 0, ""

    content, status = _fetch_rss_bytes(RSS_URL.format(channel_id=cid))
    if content is None:
        hint = " — 없는 채널 id 로 보입니다" if status == 404 else ""
        return f"가져오기 실패 (status={status}){hint}", 0, ""

    feed = feedparser.parse(content)
    name = (feed.feed.get("title") or "").strip()
    n = len(feed.entries)
    if n == 0:
        return "응답은 되는데 영상이 0건", 0, name
    return "OK", n, name


def main() -> int:
    warn_only = "--warn" in sys.argv
    bad, mismatch = [], []
    print(f"채널 점검 — 등록 {len(CHANNELS)}개")
    for ch in CHANNELS:
        state, n, real = probe(ch)
        mark = "OK" if state == "OK" else "✗ "
        note = ""
        if state == "OK" and real and real != ch["name"]:
            # 이름이 다르다고 틀린 것은 아니다(우리가 부르는 이름을 쓸 수 있다).
            # 다만 엉뚱한 채널을 넣었을 때 이걸로 바로 알아챌 수 있다.
            note = f"  ← 채널이 밝히는 이름: '{real}'"
            mismatch.append((ch["name"], real))
        print(f"  {mark} {ch['name']:<20} {state:<34}"
              f"{f'영상 {n}건' if n else ''}{note}")
        if state != "OK":
            bad.append((ch["name"], ch.get("channel_id", ""), state))

    if mismatch:
        print(f"\n참고 — 설정한 이름과 채널이 밝히는 이름이 다른 곳 {len(mismatch)}개입니다.")
        print("  우리가 부르는 이름을 쓴 것이면 그대로 두셔도 됩니다.")
        print("  전혀 다른 채널이면 channel_id 를 잘못 넣은 것입니다.")

    if not bad:
        print("\n모든 채널 정상")
        return 0
    print(f"\n문제가 있는 채널 {len(bad)}개:", file=sys.stderr)
    for name, cid, state in bad:
        print(f"  {name} (id={cid}) — {state}", file=sys.stderr)
    return 0 if warn_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
