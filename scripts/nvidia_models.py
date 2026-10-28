"""NVIDIA(NIM) — 텍스트 처리의 <2순위> 예비 경로. GitHub Models 다음, Gemini·OpenAI 앞이다.

순서가 왜 이런가 (사용자 지정, 2026-10-28)
  GitHub Models(무료) → NVIDIA → Gemini(텍스트) → OpenAI(과금, 마지막).
  Gemini 를 완전히 건너뛰지는 않는다 — 유튜브 영상을 <직접> 보는 것은 구글
  서버가 영상을 가져오는 Gemini 고유 기능이라, 자막·설명이 없는 영상은
  여기서도 끝까지 Gemini 몫이다. 이 경로는 '자막·설명글이 있는 영상의
  텍스트 처리'만 넘겨받는다.

등록 (저장소 Settings → Secrets and variables → Actions)
  KTH_01_NVIDIA_API_KEY      ← 하나만 쓸 거면 이 이름 하나로 충분하다
  KTH_01_NVIDIA_API_KEY_2    ← 둘 이상이면 뒤에 번호를 붙인다 (다른 키 모듈과 같은 규칙)
  KTH_01_NVIDIA_API_KEY_3
  ...
  ※ KEY1·KEY2 처럼 밑줄 없이 붙이면 인식되지 않는다 — 반드시 KEY_2 형태.

  한 키가 한도·잔액으로 막히면(401·429) 다음 키로 갈아탄다.

build.nvidia.com(NIM API 카탈로그) 키는 OpenAI 호환 엔드포인트를 쓴다 —
그래서 openai_models.py 와 거의 같은 모양이다. 다른 것은 주소와 기본 모델뿐이다.

키가 없어도 파이프라인은 지금과 똑같이 돈다(예비 경로가 하나 적을 뿐이다).
"""
from __future__ import annotations

import json
import os
import sys

ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"

# llama-3.2-90b-vision-instruct 는 테스트 호출(간단한 프롬프트)조차 180초
# 타임아웃 안에 응답을 못 줬다(2026-10-28, ReadTimeout). 비전 모델은 90B 급이라
# NIM 서버 콜드스타트·처리 지연이 크고, 실제 리포트 프롬프트(1만자 안팎)는
# 그보다 훨씬 길어 사실상 쓸 수 없었다. 우리 쓰임새는 자막 텍스트 요약뿐이라
# 이미지 인식이 필요 없으므로, 더 가볍고 빠른 순수 텍스트 모델로 바꾼다.
# NVIDIA_MODEL 로 바꿀 수 있다.
DEFAULT_MODEL = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-8b-instruct")
TIMEOUT_SEC = int(os.getenv("NVIDIA_TIMEOUT_SEC", "180"))
MAX_KEYS = 10

# 연속 실패하면 접는다 — 키가 전부 틀렸거나 잔액이 없으면 매번 같은 이유로 실패한다.
FAIL_LIMIT = 3
_fails = 0

# 이번 실행에서 이 경로를 몇 번 썼는지.
_used = 0

_keys: list[str] = []
_pos = 0
_spent: set[int] = set()        # 이번 실행에서 막힌(401·429) 키


class NvidiaUnavailable(Exception):
    """이 경로를 쓸 수 없다 — 호출자는 원래 오류를 그대로 올리면 된다."""


def _collect() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        v = (v or "").strip()
        if v and v not in seen:      # 같은 키를 두 번 넣어 봐야 한도는 하나다
            seen.add(v)
            out.append(v)

    add(os.getenv("NVIDIA_API_KEY", ""))
    for i in range(2, MAX_KEYS + 1):
        add(os.getenv(f"NVIDIA_API_KEY_{i}", ""))
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


def list_models() -> list[str]:
    """이 키로 지금 실제 쓸 수 있는 모델 id 목록.

    NIM 카탈로그는 모델을 수시로 은퇴시킨다 — DEFAULT_MODEL 을 문서·추측으로
    적어 두면 또 '모델이 사라진 줄 모르고 계속 틀리는' 일이 반복된다
    (2026-10-28 에 llama-3.2-90b-vision-instruct 는 타임아웃, 그다음 고른
    llama-3.1-8b-instruct 는 8월에 이미 단종돼 있었다). 실패했을 때 이 목록을
    찍어, 다음 모델은 추측이 아니라 지금 살아 있는 것 중에서 고르게 한다.
    """
    import requests
    res = requests.get("https://integrate.api.nvidia.com/v1/models",
                       headers={"Authorization": f"Bearer {token()}"}, timeout=30)
    res.raise_for_status()
    return sorted(m.get("id", "") for m in res.json().get("data", []))


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
    """프롬프트를 넘기고 응답 문자열을 받는다.

    키가 여러 개면 401(키 오류)·429(한도·잔액)에서 다음 키로 갈아타며,
    전부 막혔을 때만 예외를 올린다.

    ※ response_format 을 강제하지 않는다. NIM 뒤에 서로 다른 모델이 있어
      json_object 모드 지원 여부가 모델마다 다르다 — 지원 안 하는 모델에
      보내면 그 요청 자체가 400 으로 거부된다. 우리 프롬프트(JSON_SPEC)가
      이미 JSON 만 출력하라고 지시하고, 호출부가 ```fence 를 벗겨 내며
      파싱하므로 강제하지 않아도 동작한다(gh_models.py 와 같은 방식).
    """
    global _fails, _used
    import requests

    while True:
        if not available():
            raise NvidiaUnavailable("키가 없거나 연속 실패로 접었습니다")
        try:
            res = requests.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {token()}",
                         "Content-Type": "application/json"},
                json={"model": DEFAULT_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.4,
                      "max_tokens": 8192},
                timeout=TIMEOUT_SEC,
            )
        except Exception as exc:  # noqa: BLE001
            _fails += 1
            raise NvidiaUnavailable(f"요청 실패 — {exc.__class__.__name__}") from exc

        if res.status_code in (401, 429):
            # 이 키로는 더 못 간다 — 틀렸거나(401) 한도·잔액이 없다(429).
            # 다음 키가 있으면 갈아타고, 없으면 지금까지와 같이 예외를 올린다.
            if _rotate():
                print(f"  [예비] NVIDIA HTTP {res.status_code} — {_label()} 로 갈아탑니다",
                      file=sys.stderr)
                continue
            detail = res.text[:200].replace("\n", " ")
            hint = " — 키가 잘못됐습니다" if res.status_code == 401 else " — 한도 또는 잔액을 확인하세요"
            raise NvidiaUnavailable(f"HTTP {res.status_code}{hint} {detail}")

        if res.status_code != 200:
            _fails += 1
            # 응답 본문에 키는 실리지 않는다(요청 헤더에만 있다).
            detail = res.text[:200].replace("\n", " ")
            raise NvidiaUnavailable(f"HTTP {res.status_code} {detail}")

        try:
            text = res.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError, json.JSONDecodeError) as exc:
            _fails += 1
            raise NvidiaUnavailable("응답을 읽지 못했습니다") from exc

        _fails = 0
        _used += 1
        print(f"  [예비] NVIDIA({DEFAULT_MODEL})로 처리했습니다 — {len(text):,}자",
              file=sys.stderr)
        return text
