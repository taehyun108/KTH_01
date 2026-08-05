"""
기존 리포트를 최신 말투(프롬프트 버전)로 다시 만든다.

reports.json 에서 pv(prompt version)가 현재 PROMPT_VERSION 보다 낮은(또는 없는) 리포트를
골라, <이미 만들어 둔 리포트 본문>을 근거로 말투만 다시 써서
'같은 파일 경로(url)·같은 id·같은 날짜'로 갈아끼운다.

※ 예전에는 원본 자막을 다시 받아 처음부터 요약했는데, 러너 IP 가 유튜브에 차단된
  환경에서는 자막을 영영 못 받아 전 건이 '근거부족'으로 실패했다(136건 중 0건 성공).
  말투를 바꾸는 데 필요한 것은 자막이 아니라 이미 쓴 본문이므로, 그것을 근거로 삼는다.
  사실을 새로 만들지 않으니 환각 위험도 오히려 낮다.
제목/요약/카테고리 등 표시 필드는 갱신하되 링크는 그대로라 즐겨찾기/북마크가 깨지지 않는다.

Gemini 일일 무료 할당량이 소진되면 그 지점에서 멈추고, 다음 실행에서 이어서 처리한다
(pv 스탬프로 이미 끝난 건 건너뜀). 며칠에 걸쳐 전체가 새 말투로 교체된다.

환경변수:
  GEMINI_API_KEY (필수)
  REGEN_MAX      (선택) 이번 실행에서 최대 몇 건까지 재생성할지. 미설정이면 할당량이 허용하는 만큼.
"""
from __future__ import annotations

import html as _html
import os
import re
import sys

from build_index import load_existing, merge
from config import NEWS_DIR
from generate_report import (
    PROMPT_VERSION, rewrite_tone, render_html, QuotaExhausted,
)
from run_pipeline import _extract_video_id


def _body_text(url: str) -> str:
    """기존 리포트 HTML 에서 본문 텍스트만 뽑는다(말투 재작성의 근거)."""
    f = NEWS_DIR / url
    if not f.exists():
        return ""
    h = f.read_text(encoding="utf-8")
    m = re.search(r"<main.*?</main>", h, re.S)
    h = m.group(0) if m else h
    h = re.sub(r"<(script|style|nav).*?</\1>", " ", h, flags=re.S)
    # 표는 '항목: 값' 형태로 살려 둔다
    h = re.sub(r"</t[dh]>", " | ", h)
    h = re.sub(r"</tr>", "\n", h)
    h = re.sub(r"</(p|h1|h2|h3|section|div)>", "\n", h)
    txt = _html.unescape(re.sub(r"<[^>]+>", " ", h))
    txt = re.sub(r"[ \t]+", " ", txt)
    return re.sub(r"\n{2,}", "\n", txt).strip()


def _needs_update(r: dict) -> bool:
    try:
        return int(r.get("pv", 0)) < PROMPT_VERSION
    except (TypeError, ValueError):
        return True


def regenerate() -> int:
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 미설정 — 재생성을 건너뜁니다.", file=sys.stderr)
        return 0

    reports = load_existing()
    todo = [r for r in reports if _needs_update(r)]
    todo.sort(key=lambda r: r.get("date", ""))  # 오래된 것부터
    limit = int(os.getenv("REGEN_MAX", "0") or 0)
    print(f"[재생성] 대상 {len(todo)}건 (전체 {len(reports)}건 중 pv<{PROMPT_VERSION})")

    updated: list[dict] = []
    for r in todo:
        if limit and len(updated) >= limit:
            break
        vid = r.get("video_id") or _extract_video_id(r.get("video", ""))
        url = r.get("url", "")
        if not vid or not url:
            continue
        body = _body_text(url)
        if len(body) < 400:
            print(f"  – 건너뜀(본문 부족 {len(body)}자) {url}", file=sys.stderr)
            continue
        meta = {
            "video_id": vid,
            "title": r.get("title", ""),
            "channel": r.get("channel", ""),
            "published": r.get("date", ""),
            "link": r.get("video", ""),
            "description": r.get("summary", ""),
        }
        try:
            data = rewrite_tone(r, body, scope=r.get("scope", "battery"))
        except QuotaExhausted:
            print(f"  ! 일일 쿼터 소진 — 여기까지 저장하고 종료 ({len(updated)}건 갱신)",
                  file=sys.stderr)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 실패 {vid}: {exc}", file=sys.stderr)
            continue

        # 같은 파일 경로에 덮어써 링크/즐겨찾기 유지 (id·url·date 보존)
        (NEWS_DIR / url).write_text(
            render_html(data, meta, r.get("date", "")), encoding="utf-8")

        r = dict(r)  # 사본에 표시 필드만 갱신
        r["title"] = data["title"]
        r["summary"] = data["meta_description"]
        r["category"] = data["category"]
        r["relation"] = data["relation"]
        r["pv"] = PROMPT_VERSION
        updated.append(r)
        print(f"  ✔ 갱신: {url}")

    if updated:
        merge(updated)  # id 기준 덮어쓰기 (나머지 리포트는 그대로 유지)
    remaining = len(todo) - len(updated)
    print(f"완료 — {len(updated)}건 새 말투로 교체, 남은 {remaining}건은 다음 실행에서 처리")
    return 0


if __name__ == "__main__":
    raise SystemExit(regenerate())
