"""등록한 키로 지금 실제로 쓸 수 있는 모델 목록을 공급자별로 찍는다(models-catalog.yml 전용).

키 값은 찍지 않는다. 모델을 바꾸기 전에 '추측'이 아니라 '지금 살아 있는 목록'에서 고르기 위한 도구다
(NVIDIA 에서 추측으로 모델을 골라 세 번 틀렸다 — nvidia_models.py 주석 참고).
"""
from __future__ import annotations

import os
import sys


def github() -> None:
    import requests
    tok = os.getenv("GITHUB_TOKEN", "")
    r = requests.get("https://models.github.ai/catalog/models", timeout=30,
                     headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                              "X-GitHub-Api-Version": "2022-11-28"})
    print(f"[GitHub Models] HTTP {r.status_code}")
    if r.status_code != 200:
        print("  ", r.text[:160].replace("\n", " "))
        return
    try:
        data = r.json()
    except ValueError:
        print("   JSON 이 아닌 응답:", r.headers.get("content-type"), r.text[:200].replace("\n", " "))
        return
    if isinstance(data, dict):
        data = data.get("models") or data.get("data") or list(data.values())
    for m in sorted(data, key=lambda x: x.get("id", "")):
        print(f"  {m.get('id'):45} tier={m.get('rate_limit_tier','?'):7} ctx={m.get('limits',{}).get('max_input_tokens','?')}"
              f" out={m.get('limits',{}).get('max_output_tokens','?')} cap={','.join(m.get('capabilities',[]))[:30]}")


def gemini() -> None:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        print("[Gemini] 키 없음"); return
    from google import genai
    print("[Gemini] generateContent 지원 모델")
    client = genai.Client(api_key=key)          # 참조를 잡아 둬야 요청 중 닫히지 않는다
    for m in client.models.list():
        acts = getattr(m, "supported_actions", None) or []
        if "generateContent" in acts:
            print("  ", m.name.split("/")[-1])


def openai() -> None:
    import requests
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        print("[OpenAI] 키 없음"); return
    r = requests.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    print(f"[OpenAI] HTTP {r.status_code}")
    if r.status_code == 200:
        ids = sorted(m["id"] for m in r.json().get("data", []))
        print("  ", ", ".join(i for i in ids if i.startswith(("gpt", "o1", "o3", "o4", "chatgpt")) and "audio" not in i
                             and "realtime" not in i and "image" not in i and "tts" not in i and "transcribe" not in i))


def nvidia() -> None:
    import nvidia_models
    print(f"[NVIDIA] 현재 기본 모델 {nvidia_models.DEFAULT_MODEL} / 키 {nvidia_models.key_count()}개")
    try:
        ids = nvidia_models.list_models()
        print("  ", len(ids), "개 중 일부:", ", ".join(i for i in ids if any(k in i for k in
              ("minimax", "llama-3.3", "llama-4", "gpt-oss", "qwen", "deepseek", "mistral-small", "gemma", "nemotron"))) [:600])
    except Exception as exc:  # noqa: BLE001
        print("   목록 조회 실패:", exc.__class__.__name__, str(exc)[:100])


if __name__ == "__main__":
    for fn in (github, gemini, openai, nvidia):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"[{fn.__name__}] 실패: {exc.__class__.__name__} {str(exc)[:120]}", file=sys.stderr)
