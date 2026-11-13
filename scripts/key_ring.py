"""API 키 돌려쓰기 — 공급자마다 복사돼 있던 규칙을 한 곳에 모았다.

규칙(공급자 공통)
  · 기본 이름 하나(<BASE>)와 번호 붙은 이름(<BASE>_2 … <BASE>_N)만 읽는다.
    ※ KEY1·KEY2 처럼 밑줄 없이 붙인 이름은 인식하지 않는다.
  · 같은 값은 하나로 센다 — 같은 키를 두 번 넣어 봐야 한도는 하나다.
  · 한도·잔액으로 막힌(401·429 등) 키는 '소진'으로 표시하고 다음 키로 넘어간다.
  · 로그에는 키 값 대신 번호만 찍는다.

공급자 모듈(gemini_keys·openai_models·nvidia_models)은 어떤 환경변수를 읽고
어디로 요청을 보내는지만 알면 된다.
"""
from __future__ import annotations

import os


class KeyRing:
    def __init__(self, base: str, *, max_keys: int = 10, csv_env: str | None = None,
                 noun: str = "막힘") -> None:
        self.base, self.max_keys, self.csv_env, self.noun = base, max_keys, csv_env, noun
        self._keys: list[str] | None = None
        self._pos = 0
        self._spent: set[int] = set()

    def _collect(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()

        def add(v: str) -> None:
            v = (v or "").strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)

        if self.csv_env:
            for v in (os.getenv(self.csv_env) or "").split(","):
                add(v)
        add(os.getenv(self.base, ""))
        for i in range(2, self.max_keys + 1):
            add(os.getenv(f"{self.base}_{i}", ""))
        return out

    def keys(self) -> list[str]:
        if not self._keys:
            self._keys = self._collect()
        return self._keys

    def count(self) -> int:
        return len(self.keys())

    def current(self) -> str:
        """지금 쓸 키. 하나도 없으면 빈 문자열."""
        ks = self.keys()
        return ks[self._pos] if self._pos < len(ks) else ""

    def label(self) -> str:
        return f"{self._pos + 1}/{self.count()}번 키"

    def rotate(self) -> bool:
        """지금 키를 소진으로 표시하고 다음 키로 넘어간다. 남은 키가 없으면 False."""
        self._spent.add(self._pos)
        for i in range(self.count()):
            if i not in self._spent:
                self._pos = i
                return True
        return False

    def spent(self) -> int:
        return len(self._spent)

    def summary(self) -> str:
        n = self.count()
        if n == 0:
            return "등록된 키 없음"
        return f"키 {n}개 중 {len(self._spent)}개 {self.noun} · 지금 {self.label()}"
