"""리포트 한 건의 <전문>을 텔레그램으로 보낸다 (01 핵심 개요 ~ 08 용어 사전 + 영상 링크).

사이트 카드의 📨 버튼이 "[전송] <리포트 id>" 이슈를 열면 워크플로가 이것을 부른다.
목록 알림(telegram_notify)이 제목·요약만 보내는 것과 달리, 여기서는 발행된 HTML 을
그대로 읽어 본문 전체를 옮긴다 — 텔레그램만 보고도 리포트를 다 읽을 수 있어야 한다.
"""
from __future__ import annotations

import html as html_mod
import os
import re
from urllib.parse import quote

import telegram_notify as tg
from build_index import load_existing
from config import NEWS_DIR, SITE_BASE_URL

SECTION_RE = re.compile(
    r'<section class="sec-card[^"]*">\s*<div class="sec-head">'
    r'<span class="sec-num">(?P<num>[^<]*)</span><h2>(?P<heading>.*?)</h2></div>'
    r'(?P<body>.*?)</section>', re.S)
ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
PARA_RE = re.compile(r"<p>(.*?)</p>", re.S)


def _text(fragment: str) -> str:
    """태그를 걷어 내고 사람이 읽는 글자만 남긴다."""
    s = re.sub(r"<br\s*/?>", " ", fragment)
    s = re.sub(r"<[^>]+>", "", s)
    return html_mod.unescape(s).strip()


def extract_sections(page: str) -> list[tuple[str, str, list[str]]]:
    """발행된 HTML → [(번호, 제목, 줄 목록)]."""
    out = []
    for m in SECTION_RE.finditer(page):
        body = m.group("body")
        rows = ROW_RE.findall(body)
        lines: list[str] = []
        if rows:
            # 표(01 개요·08 용어 사전) — thead 의 머리글 행은 td 가 없어 저절로 빠진다
            for row in rows:
                cells = [_text(c) for c in CELL_RE.findall(row)]
                cells = [c for c in cells if c]
                if cells:
                    lines.append(" — ".join(cells))
        else:
            lines = [t for p in PARA_RE.findall(body) if (t := _text(p))]
        out.append((_text(m.group("num")), _text(m.group("heading")), lines))
    return out


def build_message(report: dict, sections: list[tuple[str, str, list[str]]]) -> list[str]:
    e = tg._escape
    cat = tg.CATEGORY_LABELS.get(report.get("category", ""), "")
    rel = tg.RELATION_LABELS.get(report.get("relation", ""), "")
    video = report.get("video", "")

    parts = ["\n".join(filter(None, [
        f"<b>{e(report.get('title'))}</b>",
        "",
        " · ".join(t for t in (cat, rel) if t),
        f"📺 {e(report.get('channel'))} · {e(report.get('date'))}",
        f'🎬 <a href="{e(video)}">유튜브 영상 보기</a>' if video else "",
    ]))]

    for num, heading, lines in sections:
        body = "\n".join(f"• {e(l)}" for l in lines) if len(lines) > 1 \
            else "\n".join(e(l) for l in lines)
        parts.append(f"<b>{e(num)}. {e(heading)}</b>\n{body}".strip())

    parts.append("\n".join(filter(None, [
        f'📄 <a href="{SITE_BASE_URL}/news/{quote(report.get("url", ""))}">'
        f'원문 리포트</a>',
        f'🎬 <a href="{e(video)}">유튜브 영상</a>' if video else "",
    ])))
    return parts


def _out(status: str, message: str) -> None:
    # 줄바꿈이 섞이면 $GITHUB_OUTPUT 의 key=value 구조가 깨져 뒤에 아무 출력이나
    # 끼워 넣을 수 있게 된다. 예외 메시지가 그대로 실리는 자리라 여기서 한 줄로 접는다.
    message = " ".join(str(message).split())[:300]
    print(f"[{status}] {message}")
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"status={status}\nmessage={message}\n")


def main() -> int:
    raw = f"{os.getenv('ISSUE_TITLE', '')}\n{os.getenv('ISSUE_BODY', '')}\n" \
          f"{os.getenv('REPORT_ID', '')}"
    m = re.search(r"\[전송\]\s*(\S.*)", raw) or re.search(r"^-?\s*id:\s*(\S+)", raw, re.M)
    report_id = (m.group(1).strip() if m else os.getenv("REPORT_ID", "").strip())
    if not report_id:
        _out("error", "보낼 리포트 id 를 찾지 못했습니다.")
        return 1

    report = next((r for r in load_existing() if r.get("id") == report_id), None)
    if report is None:
        _out("notfound", f"'{report_id}' 리포트를 아카이브에서 찾지 못했습니다.")
        return 0

    page_file = NEWS_DIR / report.get("url", "")
    if not page_file.exists():
        _out("notfound", f"리포트 파일이 없습니다 — {report.get('url')}")
        return 0

    sections = extract_sections(page_file.read_text(encoding="utf-8"))
    if not sections:
        _out("error", "리포트 본문(01~08)을 읽지 못했습니다.")
        return 1

    if not tg.enabled():
        _out("error", "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 시크릿이 없습니다.")
        return 1

    try:
        n = tg.send_text(build_message(report, sections))
    except Exception as exc:  # noqa: BLE001
        _out("error", f"전송 실패 — {exc}")
        return 1

    _out("ok", f"텔레그램으로 보냈습니다 — 본문 {len(sections)}개 섹션, 메시지 {n}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
