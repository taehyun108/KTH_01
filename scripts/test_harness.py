"""회귀 검사 실행 틀 — 검사 자동 수집 · 검사별 격리 · 집계.

예전에는 main() 이 check_* 를 하나하나 손으로 부르고, 통과 개수를 주석 달린 덧셈식으로
맞췄다(검사를 추가할 때마다 숫자를 손으로 올렸다). 또 일부 검사가 requests 모듈이나 환경변수를
바꿔 둔 채 끝나, 뒤에 오는 검사가 오염된 상태에서 돌았다(2026-11-13 에 실제로 부딪힘).

여기서는
  · check_ 로 시작하는 함수를 모듈에서 자동으로 모으고
  · 검사마다 환경변수·sys.modules['requests']·작업 폴더를 원래대로 되돌리며
  · 검사가 예외로 죽어도 실행 전체를 멈추지 않고 실패로 기록한다.
"""
from __future__ import annotations

import os
import sys
import traceback
from typing import Callable

_MISSING = object()


def collect(namespace: dict, module_name: str) -> list[tuple[str, Callable[[], list[str]]]]:
    """namespace 안의 check_* 함수를 정의 순서대로 모은다(다른 모듈에서 가져온 것은 제외)."""
    return [(n, f) for n, f in namespace.items()
            if n.startswith("check_") and callable(f)
            and getattr(f, "__module__", None) in (module_name, "__main__")]


def isolated(fn: Callable[[], list[str]]) -> list[str]:
    """fn 을 돌리고, 끝나면 환경변수·requests 모듈·작업 폴더를 원래대로 되돌린다."""
    env = dict(os.environ)
    req = sys.modules.get("requests", _MISSING)
    cwd = os.getcwd()
    try:
        return fn()
    finally:
        os.environ.clear()
        os.environ.update(env)
        if req is _MISSING:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = req
        os.chdir(cwd)


def run(checks: list[tuple[str, Callable[[], list[str]]]]) -> tuple[list[str], int, int]:
    """(실패 메시지들, 검사 수, 실패한 검사 수)."""
    fails: list[str] = []
    bad = 0
    for name, fn in checks:
        try:
            got = isolated(fn)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            got = [f"  [{name}] 검사가 예외로 중단됐습니다 — {exc.__class__.__name__}: {str(exc)[:120]}"]
        if got:
            bad += 1
            fails += got
    return fails, len(checks), bad
