"""Gemini 영상 직접 분석 예산을 <하루 단위·분 기준>으로 관리한다.

왜 건수가 아니라 분인가
  무료 티어가 재는 것은 <처리한 영상 길이>다(대략 하루 8시간). 그런데 우리는
  '실행당 5건'이라는 건수로 막고 있었다. 이 숫자는 하루 2회 실행이던 시절에
  40분 × 5건 × 2회 ≈ 6.7시간으로 잡은 것인데, 지금은 하루 4회를 돈다.
  산식이 이미 맞지 않는다.

  건수로 재면 두 방향으로 다 틀린다.
    · 7분짜리 5건(35분)을 처리하고도 "다 썼다"며 멈춘다
    · 40분짜리 5건(200분)이면 생각보다 훨씬 많이 쓴다

  2026-08-18 실행이 정확히 앞엣것이었다. 상한 5건에 걸려 9건이 보류됐는데
  <실패는 0건>이었다. 진짜 쿼터가 아니라 우리가 건 숫자가 막은 것이다.

왜 파일로 남기는가
  실행마다 컨테이너가 새로 뜨므로 메모리로는 하루를 이어 셀 수 없다.
  site/data 에 두고 커밋한다 — skipped.json 과 같은 이유다.

날짜가 바뀌면 저절로 0 부터 시작한다.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone

from config import DATA_DIR

BUDGET_JSON = DATA_DIR / "video_budget.json"

# 하루에 쓸 영상 분(minutes). 무료 티어 추정치(약 8시간=480분)에서 여유를 뒀다.
DAILY_MINUTES = int(os.getenv("VIDEO_MINUTES_PER_DAY", "420"))
# 길이를 끝내 모를 때 잡아 둘 값. 모르면 <크게> 잡는 편이 안전하다.
UNKNOWN_MINUTES = 40


def _today() -> str:
    # 쿼터는 UTC 기준으로 초기화된다고 보고 맞춘다.
    return datetime.now(timezone.utc).date().isoformat()


def load() -> dict:
    try:
        data = json.loads(BUDGET_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if data.get("date") != _today():
        return {"date": _today(), "minutes": 0.0, "count": 0}
    return {"date": data["date"],
            "minutes": float(data.get("minutes") or 0.0),
            "count": int(data.get("count") or 0)}


def save(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BUDGET_JSON.write_text(
        json.dumps({"date": state["date"],
                    "minutes": round(state["minutes"], 1),
                    "count": state["count"]}, ensure_ascii=False, indent=1),
        encoding="utf-8")


def cost_minutes(duration_sec, cap_minutes: int) -> float:
    """이 영상을 보는 데 잡아 둘 분. 길이를 모르면 넉넉히 잡는다."""
    try:
        sec = float(duration_sec)
    except (TypeError, ValueError):
        return float(min(UNKNOWN_MINUTES, cap_minutes))
    if sec <= 0:
        return float(min(UNKNOWN_MINUTES, cap_minutes))
    return min(sec / 60.0, float(cap_minutes))


def left(state: dict) -> float:
    return max(0.0, DAILY_MINUTES - state["minutes"])


def can_afford(state: dict, minutes: float) -> bool:
    # 남은 예산이 조금이라도 있으면 한 건은 시도한다. 40분짜리 하나 때문에
    # 남은 30분을 통째로 버리는 것이 더 아깝다.
    return left(state) > 0


def charge(state: dict, minutes: float) -> None:
    state["minutes"] += minutes
    state["count"] += 1


def summary(state: dict) -> str:
    return (f"오늘 영상 분석 {state['count']}건 · "
            f"{state['minutes']:.0f}분 사용 / {DAILY_MINUTES}분 "
            f"(남음 {left(state):.0f}분)")
