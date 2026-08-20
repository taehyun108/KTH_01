"""문장 어미가 한쪽으로 쏠렸는지(=딱딱하게 읽히는지) 기계적으로 잰다.

왜 필요한가: 말투를 '~해요 → ~합니다' 처럼 어미만 바꾸면 문장의 90% 이상이
같은 소리로 끝나 뚝뚝 끊겨 읽힌다. 사람 눈에는 잘 안 보이지만 숫자로는 바로 보인다.
그래서 발행물을 훑어 '어미 쏠림'과 '같은 어미 연속'을 재고, 기준을 넘으면 알린다.

  실행: python scripts/check_tone.py                 (현재 말투 버전 리포트만 검사)
        python scripts/check_tone.py --all           (버전 무관 전체 통계)
        python scripts/check_tone.py <파일.html> ...  (특정 파일만)

CI 에서는 기본 모드로 돈다. 옛 버전 리포트는 재생성 대기 중이므로 검사하지 않는다.
"""
from __future__ import annotations

import html as _html
import json
import re
import sys
from collections import Counter
from pathlib import Path

# 어미 쏠림 기준 — 넘으면 '딱딱하다'로 본다
MAX_TOP_RATIO = 0.80      # 한 어미가 전체 문장에서 차지하는 비율 상한
MAX_RUN = 3               # 같은 어미가 연속으로 나올 수 있는 최대 문장 수
MAX_FAMILY_RATIO = 0.85   # '~니다' 계열 상한 — 손으로 쓰는 문서(용어집)에 적용
# 자동 생성 리포트는 실행마다 편차가 있어, 86% 같은 아슬아슬한 값으로 CI 를 빨갛게
# 만들면 '늘 실패하는 워크플로'가 되어 정작 진짜 고장을 놓치게 된다. 프롬프트가
# 망가졌다고 볼 만한 수준(사실상 전부 같은 어미)에서만 실패시킨다.
MAX_FAMILY_RATIO_GENERATED = 0.92

# '합니다/입니다/습니다/집니다…' 는 글자만 다를 뿐 읽을 때 같은 소리로 끝난다.
# 개별 어미로 세면 고르게 보이지만 실제로는 전부 한 계열이라 뚝뚝 끊겨 읽힌다.
# 그래서 계열 단위로도 쏠림을 잰다.
FAMILY_NIDA = "니다"

# 문장 끝에서 떼어 낼 어미들. 긴 것부터 봐야 '합니다'가 '니다'로 뭉뚱그려지지 않는다.
ENDINGS = [
    "습니다만", "했습니다", "하겠습니다", "보겠습니다", "입니다", "습니다", "합니다",
    "됩니다", "집니다", "옵니다", "givens",  # (자리표시자 없음)
    "인데요", "인가요", "일까요", "할까요", "는데요", "군요", "고요", "죠", "지요",
    "셈입니다", "때문입니다", "보입니다", "합니다만", "니다", "해요", "예요", "에요",
    "이다", "한다", "된다", "였다", "있다", "없다",
]
ENDINGS = [e for e in ENDINGS if e != "givens"]
ENDINGS.sort(key=len, reverse=True)


def _prose(path: Path) -> str:
    h = path.read_text(encoding="utf-8")
    m = re.search(r"<main.*?</main>", h, re.S)
    h = m.group(0) if m else h
    h = re.sub(r"<(script|style|nav|svg|table).*?</\1>", " ", h, flags=re.S)
    return _html.unescape(re.sub(r"<[^>]+>", " ", h))


def sentences(text: str) -> list[str]:
    out = []
    for s in re.split(r"(?<=[.!?。])\s+|\n+", text):
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) >= 12 and re.search(r"[가-힣]", s):
            out.append(s)
    return out


def ending_of(sentence: str) -> str:
    body = sentence.rstrip(" .!?…\"'’”)")
    for e in ENDINGS:
        if body.endswith(e):
            return e
    return ""


def measure(text: str) -> dict:
    ends = [e for e in (ending_of(s) for s in sentences(text)) if e]
    counts = Counter(ends)
    total = len(ends)
    # 같은 어미가 몇 문장까지 연달아 나왔는지
    longest, run, prev = 0, 0, None
    for e in ends:
        run = run + 1 if e == prev else 1
        prev = e
        longest = max(longest, run)
    top, top_n = (counts.most_common(1)[0] if counts else ("", 0))
    nida = sum(n for e, n in counts.items() if e.endswith(FAMILY_NIDA))
    return {
        "total": total, "counts": counts, "top": top,
        "ratio": (top_n / total) if total else 0.0,
        "family_ratio": (nida / total) if total else 0.0,
        "longest_run": longest, "variety": len(counts),
    }


def verdict(m: dict, generated: bool = False) -> list[str]:
    """기준을 넘긴 항목들. generated=True 면 자동 생성물용 완화 기준을 쓴다."""
    bad = []
    if m["total"] < 8:
        return bad  # 표본이 너무 적으면 판단하지 않는다
    limit = MAX_FAMILY_RATIO_GENERATED if generated else MAX_FAMILY_RATIO
    if m["ratio"] > MAX_TOP_RATIO:
        bad.append(f"어미 '{m['top']}' 쏠림 {m['ratio']:.0%}"
                   f" (상한 {MAX_TOP_RATIO:.0%})")
    if m["family_ratio"] > limit:
        bad.append(f"'~니다' 계열 쏠림 {m['family_ratio']:.0%}"
                   f" (상한 {limit:.0%}) — 어미를 섞을 것")
    if m["longest_run"] > MAX_RUN:
        bad.append(f"같은 어미 {m['longest_run']}문장 연속 (상한 {MAX_RUN})")
    return bad


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check_all = "--all" in sys.argv

    # (경로, 자동 생성물인가) — 생성물은 실행마다 편차가 있어 기준을 달리 적용한다
    if args:
        targets = [(Path(a), False) for a in args]
        label = "지정 파일"
    else:
        from config import NEWS_DIR, REPORTS_JSON
        from generate_report import PROMPT_VERSION
        data = json.loads(REPORTS_JSON.read_text(encoding="utf-8"))
        targets, skipped = [], 0
        for r in data.get("reports", []):
            p = NEWS_DIR / f"{r.get('id','')}.html"
            if not p.exists():
                continue
            if not check_all and int(r.get("pv", 0)) < PROMPT_VERSION:
                skipped += 1
                continue
            targets.append((p, True))
        label = "전체" if check_all else f"pv={PROMPT_VERSION}"
        if not check_all:
            print(f"[말투] 옛 말투(pv<{PROMPT_VERSION}) {skipped}건은 재생성 대기 — 검사 제외")
        # 손으로 쓴 문서는 재생성 대상이 아니다. 항상, 엄격한 기준으로 본다.
        #   (2026-08-18: 통상현황을 추가했다. 새 손글씨 페이지는 여기 한 줄만 더하면 된다)
        for folder in ("glossary", "trade"):
            hand = NEWS_DIR.parent / folder / "index.html"
            if hand.exists():
                targets.append((hand, False))

    def _label(path, generated: bool) -> str:
        # 손으로 쓴 문서는 전부 index.html 이라 파일명만으로는 어느 쪽인지 알 수 없다.
        # 2026-08-18 에 실제로 "index.html: 쏠림 85%" 만 찍혀 어느 페이지인지 몰랐다.
        return path.name if generated else f"{path.parent.name}/{path.name}"

    fails, warns, gen_fails = [], [], []
    agg = Counter()
    for p, generated in targets:
        m = measure(_prose(p))
        agg.update(m["counts"])
        for msg in verdict(m, generated=generated):
            # 생성물과 손으로 쓴 문서를 갈라 담는다 (아래 main 끝 주석 참고)
            (gen_fails if generated else fails).append(f"  {_label(p, generated)}: {msg}")
        # 실패는 아니지만 엄격 기준은 넘긴 생성물 — 프롬프트를 손볼 신호로 남긴다
        if generated and not verdict(m, generated=True) \
                and m["family_ratio"] > MAX_FAMILY_RATIO:
            warns.append(f"  {_label(p, generated)}: '~니다' 계열 {m['family_ratio']:.0%}"
                         f" (권장 {MAX_FAMILY_RATIO:.0%} 이하)")

    tot = sum(agg.values())
    print(f"말투 검사 — {label} {len(targets)}개 문서 · 문장 {tot}개")
    if tot:
        for e, n in agg.most_common(8):
            print(f"    {e:<8} {n:>5}  {n / tot:>5.1%}")
        fam = sum(n for e, n in agg.items() if e.endswith(FAMILY_NIDA))
        print(f"    → '~니다' 계열 합계 {fam}/{tot} = {fam / tot:.0%}"
              f" (권장 {MAX_FAMILY_RATIO:.0%} / 생성물 상한 {MAX_FAMILY_RATIO_GENERATED:.0%})")
    if warns:
        print(f"\n⚠ 권장 기준을 넘긴 생성물 {len(warns)}건 (실패는 아님):")
        for w in warns[:20]:
            print(w)
    # 생성물의 쏠림은 <알리되 막지 않는다>.
    #
    # ※ 2026-08-15~17: 리포트 한 건이 어미 100% 로 나왔고, 재생성을 돌려도
    #   같은 결과여서 스스로 고쳐지지 않았다. 그 한 건 때문에 예약 실행이
    #   6회 연속 '실패'로 표시됐다. 그러면 정작 <진짜 고장>이 났을 때
    #   빨간불이 파묻혀 구분이 안 된다. 실패 표시는 사람이 손댈 수 있는 것에만 쓴다.
    #   생성물은 프롬프트를 고쳐야 하는 문제라, 크게 알리고 넘어간다.
    if gen_fails:
        print(f"\n‼ 어미가 심하게 쏠린 생성물 {len(gen_fails)}건 "
              f"— 프롬프트를 손볼 신호입니다(실행은 막지 않습니다):", file=sys.stderr)
        for f in gen_fails[:40]:
            print(f, file=sys.stderr)

    # 손으로 쓴 문서(용어집)는 우리가 바로 고칠 수 있으므로 그대로 실패시킨다.
    if fails:
        print(f"\n어미가 쏠린 문서 {len(fails)}건:", file=sys.stderr)
        for f in fails[:40]:
            print(f, file=sys.stderr)
        return 1
    print("통과 — 어미 쏠림 없음"
          + (f" (생성물 경고 {len(gen_fails)}건)" if gen_fails else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
