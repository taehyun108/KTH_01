"""
로컬 모델 다운로드 스크립트 (오프라인 대비).

first_time_setup.bat 에서 호출되며, 인터넷이 가능한 환경에서
BGE-M3 / OmniParser / PaddleOCR 모델을 프로젝트 내부 ./models/ 로 내려받는다.

⚠️ 포터블 원칙:
  - 모든 경로는 이 파일 위치 기준 상대경로(Path(__file__)) 로 계산한다.
  - 시스템 환경변수/절대경로/드라이브 문자에 의존하지 않는다.

※ 본 스크립트는 STEP 10 에서 실제 다운로드 로직으로 채워진다.
   현재는 폴더 구조 검증용 스텁(stub)이며, 폐쇄망에서 실패해도
   앱 실행에는 지장이 없도록 항상 정상 종료(0)한다.
"""
from __future__ import annotations

from pathlib import Path

# 프로젝트 루트 = 이 파일(scripts/download_models.py) 의 부모의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"


def main() -> int:
    """모델 폴더 존재만 확인하는 스텁. (STEP 10 에서 실제 구현)"""
    print("[download_models] 모델 폴더를 확인합니다:", MODELS_DIR)
    for name in ("bge-m3", "omniparser"):
        target = MODELS_DIR / name
        target.mkdir(parents=True, exist_ok=True)
        has_files = any(p for p in target.iterdir() if p.name != ".gitkeep")
        state = "이미 준비됨" if has_files else "비어 있음 (STEP 10 에서 다운로드 예정)"
        print(f"  - {name}: {state}")
    print("[download_models] 완료. (스텁 - 실제 다운로드는 STEP 10)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
