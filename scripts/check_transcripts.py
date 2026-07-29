"""
자막 확보 경로를 '실제 실행 환경'에서 점검하는 진단 도구 (Gemini 미사용 = 쿼터 0 소비).

왜 필요한가: 자막 수집은 유튜브 네트워크에 의존해 로컬에서 검증할 수 없다.
로컬 단위 테스트만 믿었다가 (1) youtube-transcript-api 1.x API 변경,
(2) 데이터센터 IP 봇 차단 을 모두 놓친 전례가 있어, GitHub Actions 에서 직접 측정한다.

사용: workflow_dispatch 로 transcript-check.yml 실행 → 요약표를 로그에서 확인.
  SAMPLE_N(기본 8): reports.json 최신순으로 몇 개 영상을 표본 점검할지.
"""
from __future__ import annotations

import os
import sys

from build_index import load_existing
from generate_report import _transcript_api, _ytdlp_transcript
from run_pipeline import _extract_video_id


def main() -> int:
    n = int(os.getenv("SAMPLE_N", "8") or 8)
    reports = sorted(load_existing(), key=lambda r: r.get("date", ""), reverse=True)

    seen: list[tuple[str, str]] = []
    for r in reports:
        vid = r.get("video_id") or _extract_video_id(r.get("video", ""))
        if vid and vid not in [v for v, _ in seen]:
            seen.append((vid, r.get("title", "")[:36]))
        if len(seen) >= n:
            break

    if not seen:
        print("점검할 영상이 없습니다.")
        return 0

    print(f"=== 자막 확보 진단 (표본 {len(seen)}건) ===")
    ok_api = ok_ytdlp = ok_desc = fail = 0

    for vid, title in seen:
        # 1) youtube-transcript-api
        api_res = ""
        try:
            api_res = _transcript_api(vid)
            api_note = f"OK {len(api_res)}자" if len(api_res) > 40 else f"짧음({len(api_res)}자)"
        except Exception as exc:  # noqa: BLE001
            api_note = f"실패 {exc.__class__.__name__}"

        # 2) yt-dlp 폴백 (api 가 성공해도 폴백 가용성까지 확인)
        yt_text, yt_src = _ytdlp_transcript(vid)
        yt_note = f"{yt_src} {len(yt_text)}자" if yt_text else "unavailable"

        if len(api_res) > 40:
            ok_api += 1
        elif yt_src == "yt-dlp-captions":
            ok_ytdlp += 1
        elif yt_src == "video-description":
            ok_desc += 1
        else:
            fail += 1

        print(f"  [{vid}] {title}")
        print(f"      transcript-api: {api_note}")
        print(f"      yt-dlp fallback: {yt_note}")

    total = len(seen)
    covered = ok_api + ok_ytdlp + ok_desc
    print("\n=== 요약 ===")
    print(f"  transcript-api 성공 : {ok_api}/{total}")
    print(f"  yt-dlp 자막 성공    : {ok_ytdlp}/{total}")
    print(f"  설명글 대체         : {ok_desc}/{total}")
    print(f"  전부 실패           : {fail}/{total}")
    print(f"  → 본문 확보율        : {covered}/{total} ({covered * 100 // total}%)")
    if fail:
        print("  ! 전부 실패한 영상이 있습니다. 위 실패 사유를 확인하세요.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
