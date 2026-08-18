"""GitHub Models — API 키 없이 쓰는 예비 추론 경로.

왜 있는가
  Gemini 무료 한도는 모델마다 다른데, 2026-08-10 실측으로 gemini-3.6-flash 는
  <하루 20건>이었습니다. 리포트 1건 = 호출 1건이라 20건은 금방 바닥납니다.
  바닥나는 순간 그날 발행이 멈추는 구조를 없애려고 예비 경로를 둡니다.

왜 키가 필요 없는가
  GitHub Actions 가 모든 실행에 자동으로 넣어 주는 GITHUB_TOKEN 을 씁니다.
  워크플로에 아래 한 줄만 있으면 그 토큰이 추론 권한을 얻습니다.

      permissions:
        models: read

  새로 만들 키도, 시크릿에 넣을 값도, 갱신할 것도 없습니다.

한계 — 이 경로가 Gemini 를 대체하지는 못합니다
  · 유튜브 영상을 <직접> 보지 못합니다. 그건 구글 서버가 영상을 가져오는
    Gemini 고유 기능이라, 자막·설명이 없는 영상은 계속 Gemini 가 맡아야 합니다.
  · 그래서 여기서는 '자막·설명글이 있는 영상의 텍스트 처리'만 넘겨받습니다.

동작하지 않아도 파이프라인은 지금과 똑같이 돕니다(예비 경로가 없을 뿐입니다).
"""
from __future__ import annotations

import json
import os
import sys

ENDPOINT = "https://models.github.ai/inference/chat/completions"

# 무료 한도는 모델 등급을 따라갑니다. 등급이 낮을수록 하루 허용 건수가 큽니다.
# 우리가 시키는 일(자막 요약과 관련성 판정)에는 작은 모델로 충분하므로
# 처리량을 우선합니다. GH_MODEL 로 바꿀 수 있습니다.
DEFAULT_MODEL = os.getenv("GH_MODEL", "openai/gpt-4.1-mini")

TIMEOUT_SEC = int(os.getenv("GH_MODELS_TIMEOUT_SEC", "180"))

# 한 실행에서 이 횟수만큼 연속 실패하면 예비 경로를 접습니다.
# (권한 미설정·한도 소진 등으로 매번 같은 이유로 실패할 때 시간을 버리지 않도록)
FAIL_LIMIT = 3
_fails = 0


class GHModelsUnavailable(Exception):
    """예비 경로를 쓸 수 없다 — 호출자는 원래 오류를 그대로 올리면 된다."""


def token() -> str:
    """Actions 가 넣어 주는 토큰. 로컬 실행에서는 보통 비어 있다."""
    return (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()


def available() -> bool:
    if _fails >= FAIL_LIMIT or not token():
        return False
    try:
        import requests  # noqa: F401
    except ImportError:
        return False
    return True


def _note_fail(why: str) -> None:
    global _fails
    _fails += 1
    if _fails == FAIL_LIMIT:
        print(f"  [예비] GitHub Models {FAIL_LIMIT}회 연속 실패 — "
              "이번 실행에서는 예비 경로를 쓰지 않습니다.", file=sys.stderr)
    else:
        print(f"  [예비] GitHub Models 실패 — {why}", file=sys.stderr)


# 마지막으로 확인한 남은 한도 한 줄 — 실행 끝 요약에 실어 보낸다.
LAST_QUOTA = ""


def _note_quota(headers) -> None:
    """응답 헤더에 실린 남은 한도를 기록한다.

    GitHub 은 헤더 이름을 여러 번 바꿔 왔으므로 아는 이름을 모두 훑는다.
    하나도 없으면 조용히 지나간다 — 없다는 사실 자체는 오류가 아니다.
    """
    global LAST_QUOTA
    if not hasattr(headers, "get"):
        return
    got = {}
    for key in ("x-ratelimit-remaining-requests", "x-ratelimit-remaining",
                "x-ratelimit-limit-requests", "x-ratelimit-limit",
                "x-ratelimit-timeremaining", "x-ratelimit-reset"):
        val = headers.get(key)
        if val:
            got[key.replace("x-ratelimit-", "")] = val
    if got:
        LAST_QUOTA = " · ".join(f"{k} {v}" for k, v in got.items())


def generate(prompt: str, model: str = "") -> str:
    """프롬프트를 넘기고 JSON 문자열을 돌려받는다.

    Gemini 쪽과 같은 계약을 지킨다 — 호출자는 반환값을 그대로 json.loads 한다.
    실패하면 GHModelsUnavailable 를 던져, 호출자가 원래 오류를 올리게 한다.
    """
    global _fails
    if not available():
        raise GHModelsUnavailable("토큰이 없거나 연속 실패로 중단된 상태")

    import requests

    model = model or DEFAULT_MODEL
    try:
        resp = requests.post(
            ENDPOINT,
            headers={
                "Authorization": f"Bearer {token()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                # 어떤 API 버전으로 이야기하는지 명시 — 서버가 바뀌어도 덜 흔들린다
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "model": model,
                "temperature": 0.4,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=TIMEOUT_SEC,
        )
    except Exception as exc:  # noqa: BLE001
        _note_fail(f"{exc.__class__.__name__}: {' '.join(str(exc).split())[:120]}")
        raise GHModelsUnavailable(str(exc)) from exc

    if resp.status_code != 200:
        body = " ".join(resp.text.split())[:200]
        # 403 은 대개 워크플로에 permissions: models: read 가 빠진 경우다.
        # 원인을 정확히 짚어 주지 않으면 '그냥 안 되네'로 끝나 버린다.
        if resp.status_code in (401, 403):
            _note_fail(f"HTTP {resp.status_code} — 워크플로에 "
                       f"'permissions: models: read' 가 있는지 확인하세요. {body}")
        elif resp.status_code == 429:
            _note_fail(f"HTTP 429 예비 경로도 한도 소진 — {body}")
        else:
            _note_fail(f"HTTP {resp.status_code} — {body}")
        raise GHModelsUnavailable(f"HTTP {resp.status_code}")

    # 남은 한도를 <반드시> 남긴다.
    #   Gemini 한도를 추측만 하다가 며칠을 버렸습니다. 실제 숫자는 429 메시지에
    #   'limit: 20' 으로 적혀 있었는데 아무도 그 줄을 안 보고 있었기 때문입니다.
    #   같은 실수를 반복하지 않으려고, 여기서는 <막히기 전에> 남은 양을 찍습니다.
    _note_quota(getattr(resp, "headers", None))

    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        _note_fail(f"응답 형식이 예상과 다름: {' '.join(resp.text.split())[:160]}")
        raise GHModelsUnavailable("응답 파싱 실패") from exc

    if not (text or "").strip():
        _note_fail("빈 응답")
        raise GHModelsUnavailable("빈 응답")

    _fails = 0
    print(f"  [예비] GitHub Models({model})로 처리했습니다 — {len(text):,}자")
    return text
