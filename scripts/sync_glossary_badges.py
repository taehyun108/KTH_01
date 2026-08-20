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


def check_tables(name: str, path, fix: bool) -> int:
    """열 폭이 실제로 먹히는 상태인지 확인한다.

    ※ 2026-08-21: 본문 <th> 에 width 를 아무리 적어도 첫 칸이 계속 넓었다.
      원인이 둘이었다.
        · CSS 가 .glossary td.k 를 24% 로 못박아 본문 지정을 덮어썼다
        · table-layout 이 없어 브라우저가 내용에 맞춰 다시 잡았다 → width 는 힌트일 뿐
      고쳐 놓아도 CSS 한 줄이면 다시 조용히 깨지므로 여기서 지킨다.
    """
    if not path.exists():
        return 0
    html = path.read_text(encoding="utf-8")
    bad = 0
    for m in re.finditer(r'<table class="(glossary[^"]*)">(.*?)</table>', html, re.S):
        cls, body = m.group(1), m.group(2)
        ths = re.findall(r"<th\b[^>]*>", body)
        if not ths:
            continue
        all_w = all("width:" in t for t in ths)
        has_fixed = "fixed" in cls.split()
        if all_w and not has_fixed:
            print(f"  [{name}] 폭을 다 적어 두고 'fixed' class 가 없습니다 "
                  "— 지정 폭이 힌트에 그칩니다", file=sys.stderr)
            bad += 1
        elif has_fixed and not all_w:
            print(f"  [{name}] 'fixed' 인데 폭이 빠진 열이 있습니다 "
                  "— 칸이 균등분할돼 깨집니다", file=sys.stderr)
            bad += 1
        ws = [int(w) for w in re.findall(r"width:(\d+)%", body)]
        if ws and sum(ws) != 100:
            print(f"  [{name}] 열 폭 합계가 {sum(ws)}% 입니다 (100 이어야 함)",
                  file=sys.stderr)
            bad += 1
    return bad


def check_css() -> int:
    """CSS 가 본문 폭 지정을 덮어쓰고 있지 않은지."""
    from config import SITE_DIR
    css = SITE_DIR / "assets" / "style.css"
    if not css.exists():
        return 0
    text = css.read_text(encoding="utf-8")
    bad = 0
    m = re.search(r"\.report \.glossary td\.k \{([^}]*)\}", text)
    if m and re.search(r"width:\s*\d+%", m.group(1)):
        print("  [CSS] .report .glossary td.k 가 폭을 고정하고 있습니다 "
              "— 본문 <th> 지정이 무시됩니다", file=sys.stderr)
        bad += 1
    if ".glossary.fixed" not in text or "table-layout: fixed" not in text:
        print("  [CSS] .glossary.fixed { table-layout: fixed } 규칙이 없습니다 "
              "— 폭이 힌트에 그칩니다", file=sys.stderr)
        bad += 1
    return bad


def main() -> int:
    fix = "--fix" in sys.argv
    total_wrong = total_secs = 0
    for name, path in PAGES.items():
        n_wrong, n_secs = check_page(name, path, fix)
        total_wrong += n_wrong
        total_secs += n_secs

    layout = check_css()
    for name, path in PAGES.items():
        layout += check_tables(name, path, fix)

    if not total_wrong and not layout:
        print(f"배지·열폭 검사 통과 — {total_secs}개 장 모두 실제 내용과 일치")
        return 0
    if layout:
        print(f"\n열 폭 설정이 어긋난 곳 {layout}건 — 손으로 고쳐야 합니다.",
              file=sys.stderr)
        if not total_wrong:
            return 1
    if fix:
        print(f"{total_wrong}건 고쳤습니다.")
        return 0
    print(f"\n배지가 실제와 다른 곳 {total_wrong}건 — "
          "python scripts/sync_glossary_badges.py --fix 로 맞출 수 있습니다.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
