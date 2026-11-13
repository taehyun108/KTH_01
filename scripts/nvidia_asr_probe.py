"""NVIDIA 호스팅 음성 인식(Riva/NIM)이 한국어를 받아 적는지 한 번 확인한다.

nvidia-asr-test.yml 에서만 실행한다(키는 Actions 시크릿). 결과를 읽을 수 있게 모든 실패를 그대로 출력한다.
테스트 음성은 gTTS 로 만든 한국어 문장이다(실제 방송보다 깨끗한 음성이라 낙관적인 시험이다).
"""
from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REF = ("오늘 코스피는 오후 두 시경 저점을 찍은 뒤 낙폭을 줄이며 5300선을 회복했습니다. "
       "외국인은 2조 7천억 원어치를 팔았고 반도체 업종이 지수를 짓눌렀습니다.")
# 이름으로 찾지 못할 때를 위한 후보(기억에 의존한 값 — 맞다는 보장이 없다)
FALLBACK_IDS = {
    "parakeet-1.1b-rnnt-multilingual(추정)": "71203149-d3b7-4460-8231-1be2543a1fca",
    "parakeet-ctc-1.1b(추정)": "1598d209-5e27-4d3c-8079-4751568b1081",
}
LANGS = ["ko-KR", "multi", "en-US"]


def norm(t: str) -> str:
    return re.sub(r"[\s.,!?]", "", t)


def make_audio(d: Path) -> Path:
    from gtts import gTTS
    mp3, wav = d / "ref.mp3", d / "ref.wav"
    gTTS(REF, lang="ko").save(str(mp3))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(mp3), "-ac", "1",
                    "-ar", "16000", "-sample_fmt", "s16", str(wav)], check=True)
    return wav


def list_functions(key: str) -> dict[str, str]:
    import requests
    out = {}
    try:
        r = requests.get("https://api.nvcf.nvidia.com/v2/nvcf/functions",
                         headers={"Authorization": f"Bearer {key}"}, timeout=30)
        print(f"[함수 목록] HTTP {r.status_code}")
        if r.status_code == 200:
            for f in r.json().get("functions", []):
                n = f.get("name", "")
                if re.search(r"parakeet|canary|asr|riva|whisper", n, re.I):
                    out[f"{n}({f.get('status','')})"] = f["id"]
        else:
            print("  ", r.text[:160].replace("\n", " "))
    except Exception as exc:  # noqa: BLE001
        print("[함수 목록] 실패:", exc.__class__.__name__, str(exc)[:100])
    return out


def try_one(label: str, fid: str, key: str, wav: Path) -> bool:
    import riva.client
    ok = False
    for lang in LANGS:
        try:
            auth = riva.client.Auth(use_ssl=True, uri="grpc.nvcf.nvidia.com:443",
                                    metadata_args=[["function-id", fid],
                                                   ["authorization", f"Bearer {key}"]])
            asr = riva.client.ASRService(auth)
            cfg = riva.client.RecognitionConfig(language_code=lang, max_alternatives=1,
                                                enable_automatic_punctuation=True)
            riva.client.add_audio_file_specs_to_config(cfg, str(wav))
            resp = asr.offline_recognize(wav.read_bytes(), cfg)
            text = " ".join(r.alternatives[0].transcript for r in resp.results).strip()
            sim = difflib.SequenceMatcher(None, norm(REF), norm(text)).ratio()
            print(f"  {label} [{lang}] 유사도 {sim:.0%}  →  {text[:90]!r}")
            ok = ok or sim >= 0.6
        except Exception as exc:  # noqa: BLE001
            msg = " ".join(str(exc).split())[:150]
            print(f"  {label} [{lang}] 실패 — {exc.__class__.__name__}: {msg}")
    return ok


def main() -> int:
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        print("NVIDIA_API_KEY 가 없습니다")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        wav = make_audio(Path(tmp))
        print(f"테스트 음성 {wav.stat().st_size:,} bytes, 기준 문장: {REF}")
        funcs = list_functions(key)
        print(f"이름으로 찾은 후보 {len(funcs)}개")
        cands = {**funcs, **{k: v for k, v in FALLBACK_IDS.items() if v not in funcs.values()}}
        good = [k for k, v in cands.items() if try_one(k, v, key, wav)]
    print("\n=== 결과 ===")
    print("한국어로 받아 적은 모델:", good or "없음")
    return 0 if good else 2


if __name__ == "__main__":
    sys.exit(main())
