"""Gemini 키 돌려쓰기 — 한 키의 하루 한도가 바닥나면 다음 키로 넘어간다.

왜 있는가
  무료 한도는 키 하나당 하루 20건 수준이다(2026-08-10 실측). 리포트 1건이
  호출 1건이라 금방 바닥나고, 바닥나는 순간 그날 발행이 멈춘다.
  특히 <영상 직접 분석>은 Gemini 고유 기능이라 다른 경로로 대체할 수 없어서,
  여기가 막히면 전체가 막힌다.

  키를 여러 개 등록해 두면 바닥난 키를 버리고 다음 키로 이어 간다.
  키마다 한도가 따로 매겨지므로 등록한 수만큼 하루 처리량이 늘어난다.

등록 방법 (저장소 Settings → Secrets and variables → Actions)
  KTH_01_GEMINI_API_KEY      ← 지금까지 쓰던 것. 그대로 두면 된다
  KTH_01_GEMINI_API_KEY_2    ← 두 번째부터는 뒤에 번호를 붙인다
  KTH_01_GEMINI_API_KEY_3
  ...

  한 줄에 쉼표로 여러 개를 넣어도 된다(GEMINI_API_KEYS).
  서로 다른 구글 계정에서 발급해야 한도가 따로 잡힌다 — 같은 계정의 키를
  여러 개 만들어 봐야 한도는 하나다.
"""
from __future__ import annotations

from key_ring import KeyRing

MAX_KEYS = 10
_ring = KeyRing("GEMINI_API_KEY", max_keys=MAX_KEYS, csv_env="GEMINI_API_KEYS", noun="소진")


def load() -> list[str]:
    return _ring.keys()


def count() -> int:
    return _ring.count()


def current() -> str:
    """지금 쓸 키. 하나도 없으면 빈 문자열."""
    return _ring.current()


def label() -> str:
    """로그용 표시 — 키 값은 절대 찍지 않는다."""
    return _ring.label()


def spend_and_rotate() -> bool:
    """지금 키를 '한도 소진'으로 표시하고 다음 키로 넘어간다.

    넘어갈 키가 있으면 True. 전부 바닥났으면 False — 호출자는 그때 접으면 된다.
    """
    return _ring.rotate()


def summary() -> str:
    return _ring.summary()
