"""
마스터 요청으로 리포트 하나를 아카이브에서 영구 삭제한다.

호출 경로: GitHub 이슈(제목 "[삭제] <report-id>")가 열리면 delete-report.yml 이 실행.
  - 입력: 환경변수 REPORT_ID(우선) 또는 ISSUE_TITLE / ISSUE_BODY 에서 id 추출
  - 처리: site/news/<id>.html 삭제 + reports.json 에서 해당 항목 제거
  - 출력: 결과를 $GITHUB_OUTPUT 에 기록해 워크플로가 이슈에 댓글로 남긴다

실제 권한은 워크플로가 '저장소 소유자가 연 이슈'만 처리하는 것으로 지켜진다.
"""
from __future__ import annotations

import json
import os
import re
import sys

from build_index import load_existing
from config import REPORTS_JSON, DATA_DIR, NEWS_DIR, CHANNELS
from datetime import datetime


def _extract_id(text: str) -> str:
    """'[삭제] 2026-08-03-어쩌고' 또는 본문 '- id: xxx' 에서 리포트 id 추출."""
    m = re.search(r"^\s*-\s*id:\s*(\S+)", text or "", re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\[삭제\]\s*(\S.*?)\s*$", (text or "").split("\n")[0])
    return m.group(1).strip() if m else ""


def _emit(status: str, message: str) -> None:
    print(f"[결과] {status}: {message}")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")
            f.write(f"message={message}\n")


def main() -> int:
    rid = (os.getenv("REPORT_ID", "").strip()
           or _extract_id(os.getenv("ISSUE_BODY", ""))
           or _extract_id(os.getenv("ISSUE_TITLE", "")))
    if not rid:
        _emit("error", "삭제할 리포트 id 를 찾지 못했습니다.")
        return 1

    rid = rid.removesuffix(".html")
    reports = load_existing()
    keep = [r for r in reports if r.get("id") != rid]
    if len(keep) == len(reports):
        _emit("notfound", f"아카이브에 없는 id 입니다: {rid}")
        return 0

    removed = next(r for r in reports if r.get("id") == rid)

    # HTML 파일 삭제
    fname = removed.get("url") or f"{rid}.html"
    f = NEWS_DIR / fname
    if f.exists():
        f.unlink()
        print(f"  삭제: site/news/{fname}")

    # 인덱스 갱신 (build_index.merge 는 삭제를 못 하므로 직접 기록)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_JSON.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "channels": [c["name"] for c in CHANNELS],
                "reports": keep,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    _emit("ok", f"삭제 완료: {removed.get('title', rid)} (남은 {len(keep)}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
