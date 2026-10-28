"""OpenAI — Gemini·GitHub Models 가 모두 막혔을 때 쓰는 마지막 예비 경로.

왜 마지막인가
  유일하게 <돈이 드는> 경로다. 앞의 둘은 무료 한도 안에서 도는데 여기는
  호출마다 과금되므로, 앞이 다 막혔을 때만 쓴다.

무엇을 못 하는가
  유튜브 영상을 <직접> 보지 못한다. 그건 구글 서버가 영상을 가져오는
  Gemini 고유 기능이라, 자막·설명이 없는 영상은 끝까지 Gemini 몫이다.
  여기서는 '자막·설명글이 있는 영상의 텍스트 처리'만 넘겨받는다.

등록 (저장소 Settings → Secrets and variables → Actions)
  KTH_01_OPENAI_API_KEY      ← 하나만 쓸 거면 이 이름 하나로 충분하다
  KTH_01_OPENAI_API_KEY_2    ← 둘 이상이면 뒤에 번호를 붙인다 (gemini_keys.py 와 같은 규칙)
  KTH_01_OPENAI_API_KEY_3
  ...
  ※ KEY1·KEY2 처럼 밑줄 없이 붙이면 인식되지 않는다 — 반드시 KEY_2 형태.

  한 키가 한도·잔액으로 막히면(401·429) 다음 키로 갈아탄다. 서로 다른
  조직/결제 계정에서 발급해야 한도가 따로 잡힌다 — 같은 계정의 키를
  여러 개 만들어 봐야 한도(잔액)는 하나다.

키가 없어도 파이프라인은 지금과 똑같이 돈다(예비 경로가 하나 적을 뿐이다).
"""
from __future__ import annotations

import json
import os
import sys

ENDPOINT = "https://api.openai.com/v1/chat/completions"

# 자막 요약·관련성 판정에는 작은 모델로 충분하다. 비용이 곧 이 경로의 제약이다.
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
TIMEOUT_SEC = int(os.getenv("OPENAI_TIMEOUT_SEC", "180"))
MAX_KEYS = 10

# 연속 실패하면 접는다 — 키가 전부 틀렸거나 잔액이 없으면 매번 같은 이유로 실패한다.
FAIL_LIMIT = 3
_fails = 0

# 이번 실행에서 이 경로를 몇 번 썼는지. 과금되는 경로라 로그에 남긴다.
_used = 0

_keys: list[str] = []
_pos = 0
_spent: set[int] = set()        # 이번 실행에서 막힌(401·429) 키


class OpenAIUnavailable(Exception):
    """이 경로를 쓸 수 없다 — 호출자는 원래 오류를 그대로 올리면 된다."""


def _collect() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        v = (v or "").strip()
        if v and v not in seen:      # 같은 키를 두 번 넣어 봐야 한도는 하나다
            seen.add(v)
            out.append(v)

    add(os.getenv("OPENAI_API_KEY", ""))
    for i in range(2, MAX_KEYS + 1):
        add(os.getenv(f"OPENAI_API_KEY_{i}", ""))
    return out


def _load() -> list[str]:
    global _keys
    if not _keys:
        _keys = _collect()
    return _keys


def key_count() -> int:
    return len(_load())


def token() -> str:
    ks = _load()
    return ks[_pos] if _pos < len(ks) else ""


def _label() -> str:
    return f"{_pos + 1}/{key_count()}번 키"


def summary() -> str:
    n = key_count()
    if n == 0:
        return "등록된 키 없음"
    return f"키 {n}개 중 {len(_spent)}개 막힘 · 지금 {_label()}"


def _rotate() -> bool:
    """지금 키를 막힌 것으로 표시하고 다음 키로 넘어간다. 더 없으면 False."""
    global _pos, _fails
    _spent.add(_pos)
    for i in range(key_count()):
        if i not in _spent:
            _pos = i
            _fails = 0
            return True
    return False


def available() -> bool:
    if _fails >= FAIL_LIMIT or not token():
        return False
    try:
        import requests  # noqa: F401
    except ImportError:
        return False
    return True


def usage() -> int:
    return _used


def generate(prompt: str) -> str:
    """프롬프트를 넘기고 JSON 문자열을 받는다.

    키가 여러 개면 401(키 오류)·429(한도·잔액)에서 다음 키로 갈아타며,
    전부 막혔을 때만 예외를 올린다.
    """
    global _fails, _used
    import requests

    while True:
        if not available():
            raise OpenAIUnavailable("키가 없거나 연속 실패로 접었습니다")
        try:
            res = requests.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {token()}",
                         "Content-Type": "application/json"},
                json={"model": DEFAULT_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "response_format": {"type": "json_object"},
                      "temperature": 0.4},
                timeout=TIMEOUT_SEC,
            )
        except Exception as exc:  # noqa: BLE001
            _fails += 1
            raise OpenAIUnavailable(f"요청 실패 — {exc.__class__.__name__}") from exc

        if res.status_code in (401, 429):
            # 이 키로는 더 못 간다 — 틀렸거나(401) 한도·잔액이 없다(429).
            # 다음 키가 있으면 갈아타고, 없으면 지금까지와 같이 예외를 올린다.
            if _rotate():
                print(f"  [예비] OpenAI HTTP {res.status_code} — {_label()} 로 갈아탑니다",
                      file=sys.stderr)
                continue
            detail = res.text[:200].replace("\n", " ")
            hint = " — 키가 잘못됐습니다" if res.status_code == 401 else " — 한도 또는 잔액을 확인하세요"
            raise OpenAIUnavailable(f"HTTP {res.status_code}{hint} {detail}")

        if res.status_code != 200:
            _fails += 1
            # 응답 본문에 키는 실리지 않는다(요청 헤더에만 있다).
            detail = res.text[:200].replace("\n", " ")
            raise OpenAIUnavailable(f"HTTP {res.status_code} {detail}")

        try:
            text = res.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            _fails += 1
            raise OpenAIUnavailable("응답을 읽지 못했습니다") from exc

        _fails = 0
        _used += 1
        print(f"  [예비] OpenAI({DEFAULT_MODEL})로 처리했습니다 — {len(text):,}자",
              file=sys.stderr)
        return text

