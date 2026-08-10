"""
파이프라인 오케스트레이터 — GitHub Actions 에서 하루 1~2회 실행.

  RSS 수집 → 1차 키워드 필터 → 자막 추출 → Claude 2차 판단·구조화 → HTML 생성
  → reports.json 인덱스 갱신

무관/애매한 건은 /drafts 로 보내 수동 확인.
"""
from __future__ import annotations

import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

from fetch_rss import collect_candidates
import seen_store
from generate_report import (process_video, QuotaExhausted, InsufficientContext,
                             MIN_CONTEXT_CHARS, VIDEO_ANALYSIS_MAX, video_usage)
from build_index import merge, load_existing
from config import MAX_CANDIDATES_PER_RUN

# 실행 시간 상한(분). 이 시간을 넘기면 처리를 멈추고, 그때까지 만든 리포트를
# 정상적으로 저장한 뒤 종료한다.
#   ※ GitHub Actions 의 job 한도(6시간)에 걸려 '취소'되면 이후 커밋 단계가 통째로
#     건너뛰어져, 이미 만들어 둔 리포트까지 버려진다(2026-08-05 저녁 실행에서 발생).
#     한도에 닿기 한참 전에 우리 손으로 끝내는 것이 안전하다.
TIME_BUDGET_MIN = int(os.getenv("PIPELINE_BUDGET_MIN", "35"))


def _extract_video_id(url: str) -> str | None:
    """watch?v=ID · shorts/ID · live/ID · youtu.be/ID · embed/ID · v/ID 에서 영상 id 추출.

    ※ 라이브 다시보기 링크(youtube.com/live/ID?si=...)에는 v= 파라미터가 없어
      예전 패턴으로는 id 를 못 뽑았다. 공유 버튼이 주는 형식이라 반드시 지원해야 한다.
    """
    for pat in (r"[?&]v=([\w-]{6,})", r"/shorts/([\w-]{6,})", r"/live/([\w-]{6,})",
                r"youtu\.be/([\w-]{6,})", r"/embed/([\w-]{6,})", r"/v/([\w-]{6,})"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    return None


def _seen_video_ids() -> set[str]:
    """이미 리포트가 만들어진 영상 id (중복 생성 방지). video_id 필드 우선, 없으면 URL 파싱."""
    seen = set()
    for r in load_existing():
        vid = r.get("video_id") or _extract_video_id(r.get("video", ""))
        if vid:
            seen.add(vid)
    return seen


def main() -> int:
    if not os.getenv("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 미설정 — 리포트 생성 단계를 건너뜁니다.", file=sys.stderr)
        return 0

    from config import BACKFILL_SINCE_DEFAULT, MAX_AGE_DAYS
    from fetch_history import collect_history
    since = os.getenv("BACKFILL_SINCE", "").strip() or BACKFILL_SINCE_DEFAULT
    if since:
        candidates = collect_history(since)
        print(f"[백필] {since} 이후 1차 후보 {len(candidates)}건 (yt-dlp)")
    else:
        # RSS 는 채널당 최신 15개만 제공해 후보가 금방 고갈된다.
        # yt-dlp 채널 목록 조회는 (자막과 달리) Actions 에서도 막히지 않으므로,
        # 최근 MAX_AGE_DAYS 일 범위를 함께 열거해 후보 풀을 넓힌다.
        rss = collect_candidates()
        cutoff = (date.today() - timedelta(days=MAX_AGE_DAYS)).isoformat()
        hist = collect_history(cutoff)
        merged = {v["video_id"]: v for v in hist}
        merged.update({v["video_id"]: v for v in rss})   # 설명이 있는 RSS 쪽을 우선
        candidates = sorted(merged.values(),
                            key=lambda v: v.get("published", ""), reverse=True)
        print(f"1차 후보 — RSS {len(rss)}건 + 최근 {MAX_AGE_DAYS}일 열거 {len(hist)}건 "
              f"→ 중복 제거 {len(candidates)}건")
    seen = _seen_video_ids()
    # 발행된 것뿐 아니라 <이미 판정이 끝난> 것도 제외한다. 그러지 않으면 30일 후보 풀
    # 안의 '무관' 영상을 매 실행 다시 Gemini 에 물어보며 하루치 쿼터를 거기서 다 쓴다.
    skip_store = seen_store.load()
    blocked = seen_store.blocked_ids(skip_store)
    print(f"  {seen_store.summary(skip_store)} → 이번 실행 제외 {len(blocked)}건")
    fresh = [c for c in candidates
             if c["video_id"] not in seen and c["video_id"] not in blocked]
    # 신규 0건일 때 원인(수집 실패인지 / 이미 처리된 것인지)을 즉시 알 수 있게 남긴다
    if not fresh:
        if not candidates:
            print("  [진단] 1차 후보 0건 — RSS 수집 실패 또는 키워드 미매치 (위 [rss] 줄 확인)",
                  file=sys.stderr)
        else:
            print(f"  [진단] 후보 {len(candidates)}건이 모두 처리 완료된 영상 — 신규 없음",
                  file=sys.stderr)

    def _round_robin(items: list, cap: float) -> list:
        """채널을 번갈아 뽑아 특정 채널 독점을 막는다 (슈카월드 등 공정 포함)."""
        by_ch: dict[str, list] = defaultdict(list)
        for c in items:
            by_ch[c["channel"]].append(c)
        for lst in by_ch.values():
            lst.sort(key=lambda c: c.get("published", ""), reverse=True)
        out: list = []
        while len(out) < cap and any(by_ch.values()):
            for ch in list(by_ch):
                if by_ch[ch]:
                    out.append(by_ch[ch].pop(0))
                    if len(out) >= cap:
                        break
        return out

    # 설명글이 충분한 후보를 <먼저> 처리한다.
    # 설명이 없는 후보는 영상 직접 분석으로 넘어가는데, 영상 쿼터는 텍스트보다 훨씬
    # 빨리 바닥난다. 순서를 섞어 두면 값싼 텍스트 후보가 뒤로 밀려, 쿼터·시간이
    # 비싼 쪽에 먼저 쓰이고 정작 만들 수 있는 것을 못 만든다.
    cap = float("inf") if MAX_CANDIDATES_PER_RUN is None else MAX_CANDIDATES_PER_RUN
    def _has_desc(c) -> bool:
        return len((c.get("description") or "").strip()) >= MIN_CONTEXT_CHARS

    with_desc = [c for c in fresh if _has_desc(c)]
    without = [c for c in fresh if not _has_desc(c)]
    fresh = _round_robin(with_desc, cap)
    if len(fresh) < cap:
        fresh += _round_robin(without, cap - len(fresh))
    print(f"  처리 순서: 설명글 충분 {len(with_desc)}건 먼저 → 영상 분석 필요 {len(without)}건")

    # 근거(자막·설명) 게이트에 전부 걸려 '신규 0건'이 나올 때 원인을 바로 알 수 있게,
    # 처리 전에 후보들이 들고 있는 설명글 길이 분포를 남긴다.
    n_none = sum(1 for c in fresh if not (c.get("description") or "").strip())
    n_thin = sum(1 for c in fresh
                 if 0 < len((c.get("description") or "").strip()) < MIN_CONTEXT_CHARS)
    n_ok = len(fresh) - n_none - n_thin
    print(f"  후보 설명글: 충분({MIN_CONTEXT_CHARS}자+) {n_ok}건 · 부족 {n_thin}건 · 없음 {n_none}건")
    if fresh and n_ok == 0:
        print("  [진단] 설명글이 충분한 후보가 0건 — 자막까지 막히면 전부 '근거부족'으로 건너뜁니다. "
              "RSS 수집(media:description)이 정상인지 위 [rss]/[hist] 줄을 확인하세요.", file=sys.stderr)

    dist = ", ".join(f"{k} {sum(1 for c in fresh if c['channel'] == k)}"
                     for k in dict.fromkeys(c["channel"] for c in fresh))
    cap_label = "무제한" if MAX_CANDIDATES_PER_RUN is None else MAX_CANDIDATES_PER_RUN
    print(f"1차 후보 {len(candidates)}건 · 신규 {len(fresh)}건 처리 (상한 {cap_label})")
    print(f"  처리 분배: {dist or '없음'}")

    new_reports = []
    n_drafts = n_error = n_skip = 0
    started = time.monotonic()
    budget = TIME_BUDGET_MIN * 60
    n_left = 0
    for i, meta in enumerate(fresh):
        if time.monotonic() - started > budget:
            n_left = len(fresh) - i
            print(f"  ! 시간 상한({TIME_BUDGET_MIN}분) 도달 — 여기서 마무리합니다 "
                  f"(남은 후보 {n_left}건은 다음 실행에서 처리)", file=sys.stderr)
            break
        try:
            result = process_video(meta)
            if result:
                print(f"  ✔ 생성: {result['id']}")
                new_reports.append(result)
            else:
                n_drafts += 1
                # 설명글만 보고 내린 '무관'은 근거가 약하다. 자막이 열리면 판단이
                # 달라질 수 있으므로 영구 배제하지 않고 나중에 다시 본다.
                reason = seen_store.irrelevant_reason(meta.get("_evidence", ""))
                seen_store.record(skip_store, meta["video_id"], reason,
                                  meta.get("title", ""))
                weak = "" if reason == seen_store.REASON_IRRELEVANT else " (나중에 재확인)"
                print(f"  – drafts(무관 판정){weak}: {meta['title'][:40]}")
        except InsufficientContext as exc:
            n_skip += 1
            seen_store.record(skip_store, meta["video_id"],
                              seen_store.REASON_NO_CONTEXT, meta.get("title", ""))
            print(f"  – 건너뜀(근거부족): {meta['title'][:38]} — {exc}", file=sys.stderr)
        except QuotaExhausted:
            print(f"  ! 일일 쿼터 소진 — 이번 실행 조기 종료 (성공 {len(new_reports)}건 저장)",
                  file=sys.stderr)
            break
        except Exception as exc:  # noqa: BLE001
            n_error += 1
            print(f"  ! 실패 {meta.get('video_id')}: {' '.join(str(exc).split())[:120]}",
                  file=sys.stderr)

    if new_reports:
        merge(new_reports)
    # 판정 결과를 남긴다. 쿼터 소진으로 중간에 끊겼더라도 여기까지의 판정은 저장해,
    # 다음 실행이 같은 영상을 처음부터 다시 물어보지 않게 한다.
    seen_store.save(skip_store)
    # 한 줄 결산 — '왜 오늘 업데이트가 적은지'를 로그 한 줄로 알 수 있게 한다
    v_ok, v_fail = video_usage()
    if n_left:
        print(f"  (시간 상한으로 {n_left}건 미처리 — 다음 실행에서 이어서 처리합니다)")
    print(f"완료 — 신규 {len(new_reports)}건 · 무관판정 {n_drafts}건 · 근거부족 건너뜀 {n_skip}건 · "
          f"오류 {n_error}건 (후보 {len(candidates)} → 신규후보 {len(fresh)})")
    print(f"  영상 직접 분석: 성공 {v_ok}건 / 실패 {v_fail}건 (실행당 상한 {VIDEO_ANALYSIS_MAX}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
