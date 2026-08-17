"""
파이프라인 오케스트레이터 — GitHub Actions 에서 하루 1~2회 실행.

  RSS 수집 → 1차 키워드 필터 → 자막 추출 → Claude 2차 판단·구조화 → HTML 생성
  → reports.json 인덱스 갱신

무관/애매한 건은 /drafts 로 보내 수동 확인.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, timedelta

from fetch_rss import collect_candidates
import seen_store
from generate_report import (process_video, QuotaExhausted, InsufficientContext,
                             NotAttempted, Throttled, MIN_CONTEXT_CHARS,
                             VIDEO_ANALYSIS_MAX, video_usage)
from build_index import merge, load_existing
from config import MAX_CANDIDATES_PER_RUN, ROOT

# 실행 시간 상한(분). 이 시간을 넘기면 처리를 멈추고, 그때까지 만든 리포트를
# 정상적으로 저장한 뒤 종료한다.
#   ※ GitHub Actions 의 job 한도(6시간)에 걸려 '취소'되면 이후 커밋 단계가 통째로
#     건너뛰어져, 이미 만들어 둔 리포트까지 버려진다(2026-08-05 저녁 실행에서 발생).
#     한도에 닿기 한참 전에 우리 손으로 끝내는 것이 안전하다.
TIME_BUDGET_MIN = int(os.getenv("PIPELINE_BUDGET_MIN", "35"))

# 빈 날이 있으면 재시도 기한을 무시하고 이만큼 다시 집어 든다.
# 하루 한 건이라도 반드시 올라오게 하기 위한 바닥선이다.
DAILY_FLOOR_THAW = int(os.getenv("DAILY_FLOOR_THAW", "12"))
# 며칠치를 되돌아보며 빈 날을 찾을지. 후보 풀(MAX_AGE_DAYS)보다 짧아야 의미가 있다.
DAILY_FLOOR_WINDOW = int(os.getenv("DAILY_FLOOR_WINDOW", "5"))


def _empty_dates(window: int = DAILY_FLOOR_WINDOW) -> set[str]:
    """최근 window 일 중 <리포트가 한 건도 없는> 날짜들.

    리포트 날짜는 영상 게시일 기준이므로(generate_report 참고), '오늘 실행했는가'가
    아니라 '그날 올라온 영상으로 만든 글이 있는가'를 본다 — 사용자가 목록에서
    보는 것이 바로 그것이다("16일자는 없고 17일자는 있네요").
    """
    have = {(r.get("date") or "")[:10] for r in load_existing()}
    today = date.today()
    return {d for i in range(window)
            if (d := (today - timedelta(days=i)).isoformat()) not in have}


# 파이프라인이 '쿼터를 더 쓸 수 있었는가'를 다음 단계(재생성)에 넘겨 주는 쪽지.
#   두 단계는 같은 job 안에서 잇달아 돌므로 파일 하나면 충분하다.
#   커밋 대상이 아니다(.gitignore) — 실행마다 새로 쓰고 버린다.
STATE_FILE = ROOT / ".pipeline_state.json"


def write_state(*, left: int, new: int, quota_hit: bool) -> None:
    """이번 실행에서 신규 발행이 쿼터·시간에 막혔는지 기록한다."""
    try:
        STATE_FILE.write_text(json.dumps(
            {"left": left, "new": new, "quota_hit": quota_hit}), encoding="utf-8")
    except OSError:
        pass        # 쪽지를 못 남겨도 파이프라인 자체는 성공이다


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


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


def order_candidates(fresh: list, cap: float, has_cache, report: bool = False,
                     empty_dates: set[str] | None = None):
    """근거가 좋은 후보부터 오도록 정렬한다.

    하루 쿼터가 빠듯해 뒤쪽 후보는 손도 못 대고 실행이 끝난다.
    즉 <어느 것을 먼저 두느냐>가 곧 그날의 발행량이다.

      1) 자막 캐시 있음 — 집 PC 가 받아 둔 전체 자막. 근거가 가장 확실해 리포트가
         실제로 나올 확률이 가장 높고, 쿼터도 텍스트 1회로 가장 싸다.
      2) 설명글 충분   — 텍스트 1회로 처리 가능. 다만 200자 설명만 보고
         '무관'으로 끝나는 일이 잦다(실측 21건).
      3) 나머지        — 영상 직접 분석으로 넘어간다. 영상 쿼터는 텍스트보다
         훨씬 빨리 바닥나므로 가장 뒤에 둔다.

    예전에는 1)에 별도 순위가 없어 3)에 섞여 맨 뒤로 밀렸다. 집 PC 로 자막을 모으는
    지금 구조에서는 가장 좋은 근거를 가장 늦게 쓰는 셈이라 순위를 앞으로 뺐다.

    각 계층 안에서는 채널을 번갈아 뽑아 한 채널이 독점하지 않게 한다.
    """
    def _has_desc(c) -> bool:
        return len((c.get("description") or "").strip()) >= MIN_CONTEXT_CHARS

    # 통째로 빈 날이 있으면 <그날 올라온 영상>을 맨 앞에 세운다.
    #   리포트 날짜는 영상 게시일을 따르므로, 빈 칸을 실제로 채우는 것은 그날 영상뿐이다.
    #   근거가 좋은 순서(아래 계층)보다 이쪽이 먼저다 — 하루를 통째로 비우는 것보다
    #   얇은 글 한 건이 낫다는 것이 정해 둔 기준이다.
    gap: list = []
    if empty_dates:
        gap = [c for c in fresh if (c.get("published") or "")[:10] in empty_dates]
        picked = {id(c) for c in gap}
        fresh = [c for c in fresh if id(c) not in picked]

    cached = [c for c in fresh if has_cache(c["video_id"])]
    rest = [c for c in fresh if not has_cache(c["video_id"])]
    with_desc = [c for c in rest if _has_desc(c)]
    without = [c for c in rest if not _has_desc(c)]

    out: list = []
    for tier in (gap, cached, with_desc, without):
        if len(out) >= cap:
            break
        out += _round_robin(tier, cap - len(out))
    if report:
        return out, (len(cached), len(with_desc), len(without), len(gap))
    return out


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
    import fetch_history
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
        # ※ 위 update 가 <쇼츠를 되살린다>. RSS 에는 길이가 없어서 표식 없는 쇼츠를
        #   못 거르는데, 길이를 보고 뺀 hist 쪽 판단을 RSS 가 그대로 덮어쓰기 때문이다.
        #   2026-08-11 에 이 경로로 쇼츠 한 건이 실제로 발행됐다.
        #   길이를 아는 쪽의 판단이 이겨야 한다 — 병합 뒤에 한 번 더 걷어 낸다.
        shorts = fetch_history.short_ids()
        revived = [v for v in merged if v in shorts]
        for vid in revived:
            del merged[vid]
        candidates = sorted(merged.values(),
                            key=lambda v: v.get("published", ""), reverse=True)
        extra = f" · RSS 가 되살린 쇼츠 {len(revived)}건 제외" if revived else ""
        print(f"1차 후보 — RSS {len(rss)}건 + 최근 {MAX_AGE_DAYS}일 열거 {len(hist)}건 "
              f"→ 중복 제거 {len(candidates)}건{extra}")

        # 열거한 후보는 설명글이 0자다(extract_flat 이 설명을 안 준다).
        # 공식 API 로 설명글과 길이를 채운다 — 후보 200건이라도 4유닛이면 끝난다.
        # 키가 없으면 아무 일도 하지 않고 지금까지처럼 진행한다.
        import yt_meta
        yt_meta.enrich(candidates, MIN_CONTEXT_CHARS)
    seen = _seen_video_ids()
    # 발행된 것뿐 아니라 <이미 판정이 끝난> 것도 제외한다. 그러지 않으면 30일 후보 풀
    # 안의 '무관' 영상을 매 실행 다시 Gemini 에 물어보며 하루치 쿼터를 거기서 다 쓴다.
    skip_store = seen_store.load()
    blocked = seen_store.blocked_ids(skip_store)
    # 집 PC 가 자막을 올려 준 영상은 재시도 기한(7일)을 기다리지 않고 즉시 다시 본다.
    # 그러지 않으면 자막을 애써 올려 놓고도 일주일간 아무 일이 일어나지 않는다.
    #
    # '근거부족'뿐 아니라 '무관(설명글만 보고 판단)'도 함께 푼다.
    #   설명글 200자만 보고 내린 무관 판정이 바로, 자막이 생기면 뒤집힐 수 있는 판단이다
    #   (seen_store.RETRYABLE 이 그래서 둘을 함께 묶고 있다).
    #   여기서 '근거부족'만 풀면, 정작 되돌려야 할 쪽을 그대로 묶어 두게 된다.
    import transcript_cache
    freed = {v for v in blocked
             if skip_store.get(v, {}).get("reason") in seen_store.RETRYABLE
             and transcript_cache.has(v)}
    blocked -= freed

    # 최근에 <통째로 빈 날>이 있으면 재시도 기한을 기다리지 않고 다시 집어 든다.
    # (2026-08-16 이 이 경우였다 — seen_store.thaw_oldest 주석 참고)
    empty = _empty_dates()
    thawed: set[str] = set()
    if empty:
        thawed = set(seen_store.thaw_oldest(skip_store, blocked, DAILY_FLOOR_THAW,
                                            prefer_dates=empty))
        blocked -= thawed
        print(f"  빈 날 {len(empty)}일({', '.join(sorted(empty))}) — "
              f"기한 전이라도 다시 봅니다")

    print(f"  {seen_store.summary(skip_store)} → 이번 실행 제외 {len(blocked)}건"
          + (f" · 자막이 새로 생겨 {len(freed)}건 해제" if freed else "")
          + (f" · 빈 날이 있어 기한 전 {len(thawed)}건 해제" if thawed else ""))
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

    cap = float("inf") if MAX_CANDIDATES_PER_RUN is None else MAX_CANDIDATES_PER_RUN
    fresh, tiers = order_candidates(fresh, cap, transcript_cache.has, report=True,
                                    empty_dates=empty)
    print("  처리 순서: "
          + (f"빈 날 메우기 {tiers[3]}건 → " if tiers[3] else "")
          + f"자막 확보 {tiers[0]}건 → 설명글 충분 {tiers[1]}건 "
            f"→ 영상 분석 필요 {tiers[2]}건")

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
    n_drafts = n_error = n_skip = n_defer = 0
    started = time.monotonic()
    budget = TIME_BUDGET_MIN * 60
    n_left = 0
    quota_hit = False
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
        except NotAttempted as exc:
            # 오늘 못 본 것뿐이다 — 판정으로 남기지 않는다.
            # 남기면 7일짜리 차단이 걸려, 원인이 사라진 뒤에도 계속 묻힌다.
            n_defer += 1
            print(f"  – 보류(판정 안 남김): {meta['title'][:38]} — {exc}", file=sys.stderr)
        except InsufficientContext as exc:
            n_skip += 1
            seen_store.record(skip_store, meta["video_id"],
                              seen_store.REASON_NO_CONTEXT, meta.get("title", ""))
            print(f"  – 건너뜀(근거부족): {meta['title'][:38]} — {exc}", file=sys.stderr)
        except Throttled:
            # 분당 제한 등 — 이 건만 건너뛰고 계속 간다(실행 전체를 접지 않는다)
            n_error += 1
            print(f"  – 건너뜀(일시 제한): {meta['title'][:38]}", file=sys.stderr)
        except QuotaExhausted:
            quota_hit = True
            n_left = len(fresh) - i
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
        # 왜 멈췄는지를 정확히 적는다. 예전에는 쿼터로 멈춘 실행도 '시간 상한'이라고
        # 찍어서, 76초 만에 끝난 실행이 '35분 상한에 걸렸다'고 말하고 있었다.
        # 원인을 잘못 가리키는 로그는 없는 로그보다 나쁘다.
        why = "일일 쿼터 소진" if quota_hit else f"시간 상한({TIME_BUDGET_MIN}분)"
        print(f"  ({why}으로 {n_left}건 미처리 — 다음 실행에서 이어서 처리합니다)")
    print(f"완료 — 신규 {len(new_reports)}건 · 무관판정 {n_drafts}건 · 근거부족 건너뜀 {n_skip}건 · "
          f"오류 {n_error}건 · 보류 {n_defer}건 (후보 {len(candidates)} → 신규후보 {len(fresh)})")
    print(f"  영상 직접 분석: 성공 {v_ok}건 / 실패 {v_fail}건 (실행당 상한 {VIDEO_ANALYSIS_MAX}건)")
    # 로그 앞부분까지 거슬러 올라가지 않고도 이번 실행의 상태를 알 수 있게,
    # 흩어져 있던 결론을 <끝에 한 줄로> 모아 둔다.
    try:
        import yt_meta as _ym
        print(f"  공식 API: {_ym.LAST}")
    except Exception:  # noqa: BLE001
        pass
    write_state(left=n_left + n_defer, new=len(new_reports), quota_hit=quota_hit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
