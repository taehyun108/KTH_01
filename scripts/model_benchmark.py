"""후보 모델에 같은 실전 과제(실제 방송 자막 요약)를 시켜 비용·속도·충실도를 비교한다(model-benchmark.yml 전용).

과제: 2026-11-12 삼프로TV 클로징벨 자막 앞부분만 근거로 JSON 요약. 정답 수치는 저점 5,293선·회복 5,300선·종가 근처 5,362선.
평가: ① JSON 이 맞는가 ② 핵심 수치(5,293·5,300·5,362)를 몇 개 살렸는가 ③ 자막에 없는 단위 수치를 지어냈는가(환각)
      ④ 소요 시간 ⑤ 토큰·추정 비용. 키 값은 출력하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import generate_report as g
import transcript_cache

KEYS = ("5293", "5300", "5362")
PRICE = {  # 100만 토큰당 USD (입력, 출력) — 2026-11 검색 기준, OpenAI 공식 페이지 확인 필요
    "gpt-6-luna": (0.10, 0.50), "gpt-5.6-luna": (0.20, 1.20), "gpt-5.4-mini": (0.75, 4.50),
    "gpt-4.1-mini": (0.40, 1.60), "gpt-4o-mini": (0.15, 0.60), "gpt-5.6-terra": (2.0, 12.0),
}
OPENAI = ["gpt-6-luna", "gpt-5.6-luna", "gpt-4o-mini", "gpt-4.1-mini"]
GITHUB = ["openai/gpt-4.1-mini", "openai/gpt-4.1", "openai/gpt-4o-mini", "openai/gpt-5-mini", "openai/gpt-5-nano"]
NVIDIA = ["minimaxai/minimax-m3.1-flash", "deepseek-ai/deepseek-v4.1-flash"]
GEMINI = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]


def prompt(text: str) -> str:
    return ("아래는 한국 증시 마감 방송의 자막 앞부분이다. 자막에 <실제로 나온> 내용만으로 JSON 한 개만 출력하라.\n"
            '{"title": "제목", "summary": "3문장 요약", "numbers": ["자막에 나온 수치 그대로"]}\n'
            "자막에 없는 수치·지수는 절대 만들지 마라.\n\n--- 자막 ---\n" + text)


def chat(url: str, key: str, model: str, p: str, openai_style: bool,
         extra: dict | None = None) -> tuple[str, int, int]:
    import requests
    body = {"model": model, "messages": [{"role": "user", "content": p}]}
    if openai_style:
        body["max_completion_tokens"] = 2000
    else:
        body["max_tokens"] = 2000
        body["temperature"] = 0.4
    hdr = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **(extra or {})}
    r = requests.post(url, headers=hdr, json=body, timeout=90)
    if r.status_code == 400 and openai_style and "max_completion_tokens" in r.text:
        body.pop("max_completion_tokens"); body["max_tokens"] = 2000
        r = requests.post(url, headers=hdr, json=body, timeout=90)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:120]}".replace("\n", " "))
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"HTTP {r.status_code} JSON 아님 type={r.headers.get('content-type')} "
                           f"body={r.text[:100]!r}") from None
    u = j.get("usage", {})
    return j["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def gemini_call(key: str, model: str, p: str) -> tuple[str, int, int]:
    from google import genai
    client = genai.Client(api_key=key)
    r = client.models.generate_content(model=model, contents=p)
    u = getattr(r, "usage_metadata", None)
    return r.text or "", getattr(u, "prompt_token_count", 0) or 0, getattr(u, "candidates_token_count", 0) or 0


def judge(raw: str, text: str) -> str:
    try:
        data = json.loads(g._strip_fences(raw))
    except ValueError:
        return "JSON✗"
    flat = json.dumps(data, ensure_ascii=False).replace(",", "")
    got = sum(1 for k in KEYS if k in flat)
    bad = g.unsupported_numbers(data, {"title": "", "description": ""}, text)
    return f"JSON✓ 핵심수치 {got}/3 환각 {len(bad)}건{bad[:4] if bad else ''}"


def run(label: str, fn, text: str, model: str, price=None) -> None:
    t = time.time()
    try:
        raw, tin, tout = fn()
    except Exception as exc:  # noqa: BLE001
        print(f"  {label:42} 실패 — {exc.__class__.__name__}: {str(exc)[:110]}")
        return
    cost = ""
    if price:
        cost = f" ≈${(tin * price[0] + tout * price[1]) / 1e6:.4f}/건"
    print(f"  {label:42} {time.time() - t:5.1f}s in{tin:>5} out{tout:>5}{cost}  {judge(raw, text)}")


def main() -> None:
    cached = transcript_cache.get("fryDxgcKcxQ")
    if not cached:
        sys.exit("cache/transcripts/fryDxgcKcxQ.json 이 없습니다")
    text = g.trim_transcript(cached[0], 6000)
    p = prompt(text)
    print(f"과제 입력 {len(text):,}자 (자막 앞부분 + 뒷부분)")
    only = os.getenv("BENCH_ONLY", "").lower()      # 예: BENCH_ONLY=gemini
    want = lambda n: not only or only == n  # noqa: E731
    k = os.getenv("OPENAI_API_KEY", "")
    if k and want("openai"):
        print("[OpenAI]")
        for m in OPENAI:
            run(m, lambda m=m: chat("https://api.openai.com/v1/chat/completions", k, m, p, True), text, m, PRICE.get(m))
    t = os.getenv("GITHUB_TOKEN", "")
    if t and want("github"):
        print("[GitHub Models — 무료, 한도 있음]")
        for m in GITHUB:
            run(m, lambda m=m: chat("https://models.github.ai/inference/chat/completions", t, m, p, False,
                                              {"Accept": "application/json", "X-GitHub-Api-Version": "2022-11-28"}), text, m)
    k = os.getenv("NVIDIA_API_KEY", "")
    if k and want("nvidia"):
        print("[NVIDIA — 무료 체험]")
        for m in NVIDIA:
            run(m, lambda m=m: chat("https://integrate.api.nvidia.com/v1/chat/completions", k, m, p, False), text, m)
    k = os.getenv("GEMINI_API_KEY", "")
    if k and want("gemini"):
        print("[Gemini]")
        for m in GEMINI:
            run(m, lambda m=m: gemini_call(k, m, p), text, m)


if __name__ == "__main__":
    main()
