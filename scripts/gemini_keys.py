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

import os

# 환경변수에서 읽을 이름들. 워크플로가 시크릿을 이 이름으로 넘긴다.
MAX_KEYS = 10

_keys: list[str] = []
_pos = 0
_spent: set[int] = set()        # 이번 실행에서 하루 한도가 바닥난 키


def _collect() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        v = (v or "").strip()
        if v and v not in seen:      # 같은 키를 두 번 넣어 봐야 한도는 하나다
            seen.add(v)
            out.append(v)

    for v in (os.getenv("GEMINI_API_KEYS") or "").split(","):
        add(v)
    add(os.getenv("GEMINI_API_KEY", ""))
    for i in range(2, MAX_KEYS + 1):
        add(os.getenv(f"GEMINI_API_KEY_{i}", ""))
    return out


def load() -> list[str]:
    global _keys
    if not _keys:
        _keys = _collect()
    return _keys


def count() -> int:
    return len(load())


def current() -> str:
    """지금 쓸 키. 하나도 없으면 빈 문자열."""
    ks = load()
    return ks[_pos] if _pos < len(ks) else ""


def label() -> str:
    """로그용 표시 — 키 값은 절대 찍지 않는다."""
    return f"{_pos + 1}/{count()}번 키"


def spend_and_rotate() -> bool:
    """지금 키를 '한도 소진'으로 표시하고 다음 키로 넘어간다.

    넘어갈 키가 있으면 True. 전부 바닥났으면 False — 호출자는 그때 접으면 된다.
    """
    global _pos
    _spent.add(_pos)
    for i in range(len(load())):
        if i not in _spent:
            _pos = i
            return True
    return False


def summary() -> str:
    n = count()
    if n == 0:
        return "등록된 키 없음"
    return f"키 {n}개 중 {len(_spent)}개 소진 · 지금 {label()}"
