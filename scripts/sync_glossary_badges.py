"""손으로 쓴 페이지의 분량 배지('그림 N · 표 N')를 실제 내용과 맞춘다.

왜 필요한가
  카드에 각 장의 그림·표 개수를 적어 두었는데, 손으로 관리하면 반드시 어긋난다.
  실제로 표를 두 개 늘리자마자 배지가 '표 4' 로 남아 틀린 값이 됐다.
  틀린 숫자는 없느니만 못하므로, 본문을 세어 다시 써 넣는다.

  대상은 용어집과 통상현황처럼 <손으로 쓰는> 페이지 전부다.
  페이지를 새로 만들 때 여기 PAGES 에 한 줄만 더하면 같은 검사를 받는다.
  (2026-08-18: 통상현황을 만들면서 배지 4곳이 곧바로 어긋났다. 손으로는 못 맞춘다.)

  실행: python scripts/sync_glossary_badges.py          (검사만, 어긋나면 실패)
        python scripts/sync_glossary_badges.py --fix    (실제로 고침)
"""
from __future__ import annotations

import re
import sys

from config import SITE_DIR

PAGES = {
    "용어집": SITE_DIR / "glossary" / "index.html",
    "통상현황": SITE_DIR / "trade" / "index.html",
}

# 장 하나 = <details id="..."> ... 다음 <details> 직전까지
SEC_OPEN = re.compile(r'<details class="sec-card full" id="([\w-]+)"[^>]*>')
SUMMARY = re.compile(
    r'(<details class="sec-card full" id="(?P<sid>[\w-]+)"[^>]*>\s*'
    r'<summary class="sec-head"><span class="sec-num">\d+</span><h2>.*?</h2>)'
    r'(?P<badge><span class="sec-meta">.*?</span>)?(?P<close></summary>)', re.S)
CARD = re.compile(
    r'(<a class="gcard" href="#(?P<sid>[\w-]+)">.*?<span class="gc-blurb">.*?</span>)'
    r'(?P<badge><span class="gc-meta">.*?</span>)?(?P<close>\s*</span>\s*</a>)', re.S)


def _badge(figs: int, tbls: int) -> str:
    bits = []
    if figs:
        bits.append(f"그림 {figs}")
    if tbls:
        bits.append(f"표 {tbls}")
    return " · ".join(bits)


def counts(html: str) -> dict[str, tuple[int, int]]:
    """각 장의 (그림 수, 표 수)."""
    opens = list(SEC_OPEN.finditer(html))
    out = {}
    for i, m in enumerate(opens):
        end = opens[i + 1].start() if i + 1 < len(opens) else len(html)
        body = html[m.start():end]
        out[m.group(1)] = (body.count("<figure"), body.count("<table"))
    return out


def check_page(name: str, path, fix: bool) -> tuple[int, int]:
    """(어긋난 건수, 장 수). 파일이 없으면 조용히 건너뛴다."""
    if not path.exists():
        return (0, 0)
    html = path.read_text(encoding="utf-8")
    real = counts(html)
    if not real:
        print(f"{name}에서 장을 찾지 못했습니다 (구조가 바뀌었나요?)", file=sys.stderr)
        return (0, 0)

    wrong: list[str] = []

    def rewrite(pat: re.Pattern, tag: str, where: str, text: str) -> str:
        def sub(m: re.Match) -> str:
            sid = m.group("sid")
            if sid not in real:
                return m.group(0)
            want = _badge(*real[sid])
            old = m.group("badge") or ""
            have = re.sub(r"<[^>]+>", "", old)
            if have != want:
                wrong.append(f"  [{name}] {sid} {where}: '{have}' → '{want}'")
            new_badge = f'<span class="{tag}">{want}</span>' if want else ""
            return m.group(1) + new_badge + m.group("close")
        return pat.sub(sub, text)

    new = rewrite(SUMMARY, "sec-meta", "제목", html)
    new = rewrite(CARD, "gc-meta", "카드", new)

    if wrong:
        for w in wrong:
            print(w, file=sys.stderr)
        if fix:
            path.write_text(new, encoding="utf-8")
    return (len(wrong), len(real))


def main() -> int:
    fix = "--fix" in sys.argv
    total_wrong = total_secs = 0
    for name, path in PAGES.items():
        n_wrong, n_secs = check_page(name, path, fix)
        total_wrong += n_wrong
        total_secs += n_secs

    if not total_wrong:
        print(f"배지 검사 통과 — {total_secs}개 장 모두 실제 내용과 일치")
        return 0
    if fix:
        print(f"{total_wrong}건 고쳤습니다.")
        return 0
    print(f"\n배지가 실제와 다른 곳 {total_wrong}건 — "
          "python scripts/sync_glossary_badges.py --fix 로 맞출 수 있습니다.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
