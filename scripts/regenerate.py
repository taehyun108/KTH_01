"""
기존 리포트를 최신 말투(프롬프트 버전)로 다시 만든다.

reports.json 에서 pv(prompt version)가 현재 PROMPT_VERSION 보다 낮은(또는 없는) 리포트를
골라, 같은 영상 자막으로 다시 요약해 '같은 파일 경로(url)·같은 id·같은 날짜'로 갈아끼운다.
제목/요약/카테고리 등 표시 필드는 갱신하되 링크는 그대로라 즐겨찾기/북마크가 깨지지 않는다.

Gemini 일일 무료 할당량이 소진되면 그 지점에서 멈추고, 다음 실행에서 이어서 처리한다
(pv 스탬프로 이미 끝난 건 건너뜀). 며칠에 걸쳐 전체가 새 말투로 교체된다.

환경변수:
  GEMINI_API_KEY (필수)
  REGEN_MAX      (선택) 이번 실행에서 최대 몇 건까지 재생성할지. 미설정이면 할당량이 허용하는 만큼.
"""
from __future__ import annotations

import os
import sys

from build_index import load_existing, merge
from config import NEWS_DIR
from generate_report import (
    PROMPT_VERSION, get_transcript, analyze, render_html, QuotaExhausted,
)
from run_pipeline import _extract_video_id


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
        if not vid:
            continue
        meta = {
            "video_id": vid,
            "title": r.get("title", ""),
            "channel": r.get("channel", ""),
            "published": r.get("date", ""),
            "link": r.get("video", ""),
            "description": "",
        }
        try:
            transcript, source = get_transcript(vid)
            data = analyze(meta, transcript, source, force=True)
        except QuotaExhausted:
            print(f"  ! 일일 쿼터 소진 — 여기까지 저장하고 종료 ({len(updated)}건 갱신)",
                  file=sys.stderr)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 실패 {vid}: {exc}", file=sys.stderr)
            continue

        # 같은 파일 경로에 덮어써 링크/즐겨찾기 유지 (id·url·date 보존)
        the_date = r.get("date", "")
        url = r.get("url", "")
        if not url:
            continue
        (NEWS_DIR / url).write_text(render_html(data, meta, the_date), encoding="utf-8")

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
