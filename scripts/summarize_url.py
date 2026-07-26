"""
사용자가 직접 제출한 유튜브 URL 하나를 요약해 아카이브에 추가한다.

호출 경로: GitHub 이슈(제목 "[요약] ...")가 열리면 summarize-url.yml 워크플로가 실행.
  - 입력: 환경변수 VIDEO_URL(우선) 또는 ISSUE_BODY(본문에서 첫 유튜브 URL 추출)
  - 처리: yt-dlp 로 메타 조회 → 기존 파이프라인 process_video(force=True) → reports.json 병합
  - 출력: 사람이 읽을 요약을 stdout 에, 머신용 결과를 $GITHUB_OUTPUT 에 기록

무관 판정 없이 항상 리포트를 생성한다(force=True) — 사용자가 명시적으로 요청했으므로.
"""
from __future__ import annotations

import os
import re
import sys

from build_index import merge, load_existing
from generate_report import process_video, QuotaExhausted
from run_pipeline import _extract_video_id

_YT_URL = re.compile(r"https?://(?:www\.)?(?:youtube\.com/\S+|youtu\.be/\S+)")


def _extract_url(text: str) -> str | None:
    m = _YT_URL.search(text or "")
    return m.group(0).rstrip(").,>]") if m else None


def _fetch_meta(url: str, video_id: str) -> dict:
    """yt-dlp 로 단일 영상 메타(제목·채널·게시일) 조회. 실패해도 최소 메타로 진행."""
    title, channel, published = "", "제출된 영상", ""
    try:
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "ignoreerrors": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        title = info.get("title") or ""
        channel = info.get("uploader") or info.get("channel") or channel
        ud = info.get("upload_date") or ""
        if isinstance(ud, str) and len(ud) == 8 and ud.isdigit():
            published = f"{ud[:4]}-{ud[4:6]}-{ud[6:]}"
        desc = info.get("description") or ""
    except Exception as exc:  # noqa: BLE001
        print(f"  [yt-dlp] 메타 조회 실패({exc}) — 최소 메타로 진행", file=sys.stderr)
        desc = ""
    return {
        "video_id": video_id,
        "title": title or f"영상 {video_id}",
        "description": desc[:2000],
        "channel": channel,
        "published": published,
        "link": url,
    }


def _emit(status: str, message: str, report_url: str = "") -> None:
    """워크플로가 이슈에 댓글로 옮길 수 있도록 결과를 GITHUB_OUTPUT 에 기록."""
    print(f"[결과] {status}: {message}")
    out = os.getenv("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"status={status}\n")
            f.write(f"message={message}\n")
            f.write(f"report_url={report_url}\n")


def main() -> int:
    if not os.getenv("GEMINI_API_KEY"):
        _emit("error", "GEMINI_API_KEY 미설정 — 요약을 실행할 수 없습니다.")
        return 1

    raw = os.getenv("VIDEO_URL", "").strip() or os.getenv("ISSUE_BODY", "")
    url = _extract_url(raw) or (raw if raw.startswith("http") else None)
    if not url:
        _emit("error", "유튜브 URL 을 찾지 못했습니다. 올바른 링크를 입력해 주세요.")
        return 1

    video_id = _extract_video_id(url)
    if not video_id:
        _emit("error", f"URL 에서 영상 ID 를 추출하지 못했습니다: {url}")
        return 1

    # 이미 아카이브에 있으면 중복 생성하지 않고 안내
    for r in load_existing():
        if (r.get("video_id") or _extract_video_id(r.get("video", ""))) == video_id:
            _emit("exists", f"이미 아카이브에 있는 영상입니다: {r.get('title', video_id)}",
                  f"news/{r.get('url', '')}")
            return 0

    meta = _fetch_meta(url, video_id)
    print(f"요약 시작 — [{meta['channel']}] {meta['title']} ({video_id})")
    try:
        result = process_video(meta, force=True)
    except QuotaExhausted:
        _emit("quota", "오늘 Gemini 일일 할당량이 소진되어 지금은 요약할 수 없습니다. "
                       "할당량 리셋 후 다시 시도해 주세요.")
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit("error", f"요약 중 오류가 발생했습니다: {exc}")
        return 1

    if not result:
        _emit("error", "리포트 생성에 실패했습니다.")
        return 1

    merge([result])
    _emit("ok", f"요약 완료: {result['title']}", f"news/{result['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
