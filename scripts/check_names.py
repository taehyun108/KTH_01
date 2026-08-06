"""이미 발행된 리포트에 옛 기관·기업 명칭이 남아 있는지 전수 검사한다.

명칭 오류는 한 번 나가면 신뢰를 크게 깎는다. 생성 단계의 프롬프트 주의만으로는
새는 곳이 생기므로, 발행물 전체를 기계적으로 다시 훑는 장치를 따로 둔다.

  실행: python scripts/check_names.py          (검사만)
        python scripts/check_names.py --fix    (옛 이름을 '옛이름(현 새이름)' 으로 교체)

CI 에서 검사 모드로 돌려, 옛 명칭이 발견되면 실패시킨다.
"""
from __future__ import annotations

import html as _html
import json
import re
import sys

from config import NEWS_DIR, REPORTS_JSON
from org_names import RENAMED, find_outdated


def _text_of(path) -> str:
    h = path.read_text(encoding="utf-8")
    m = re.search(r"<main.*?</main>", h, re.S)
    h = m.group(0) if m else h
    h = re.sub(r"<(script|style|nav).*?</\1>", " ", h, flags=re.S)
    return _html.unescape(re.sub(r"<[^>]+>", " ", h))


def scan() -> list[tuple[str, str, str]]:
    """(파일명, 옛 이름, 현재 이름) 목록."""
    out = []
    for f in sorted(NEWS_DIR.glob("*.html")):
        if f.name == "index.html":
            continue
        for old, new in find_outdated(_text_of(f)):
            out.append((f.name, old, new))
    # 목록(reports.json)의 제목·요약도 함께 본다
    data = json.loads(REPORTS_JSON.read_text(encoding="utf-8"))
    for r in data.get("reports", []):
        blob = f"{r.get('title','')} {r.get('summary','')} {r.get('channel','')}"
        for old, new in find_outdated(blob):
            out.append(("reports.json:" + r.get("id", "?"), old, new))
    return out


def fix() -> int:
    """옛 이름을 '옛이름(현 새이름)' 으로 바꾼다. 원문 인용을 지우지 않는 방식."""
    n = 0
    for f in sorted(NEWS_DIR.glob("*.html")):
        if f.name == "index.html":
            continue
        h = f.read_text(encoding="utf-8")
        orig = h
        for old, new, _, _ in RENAMED:
            if old not in h or new in h:
                continue
            # 이미 병기된 것은 건드리지 않는다
            h = re.sub(rf"{re.escape(old)}(?!\s*\(현)", f"{old}(현 {new})", h)
        if h != orig:
            f.write_text(h, encoding="utf-8")
            n += 1
    print(f"[명칭] {n}개 파일 교정")
    return n


def main() -> int:
    if "--fix" in sys.argv:
        fix()
        return 0
    hits = scan()
    if not hits:
        print(f"명칭 검사 통과 — 등록된 변경 {len(RENAMED)}건 기준, 옛 명칭 사용 0건")
        return 0
    print(f"옛 명칭 {len(hits)}건 발견:", file=sys.stderr)
    for where, old, new in hits:
        print(f"  {where}\n      '{old}' → 현재는 '{new}'", file=sys.stderr)
    print("\n  scripts/check_names.py --fix 로 '옛이름(현 새이름)' 병기 교정이 가능합니다.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
