"""
로컬 모델 다운로드 스크립트 (오프라인 대비).

`first_time_setup.bat` 에서 호출되며, 인터넷이 가능한 환경에서
필요한 AI 모델을 프로젝트 내부 `./models/` 로 내려받는다.

내려받는 모델
-------------
  1. BGE-M3        : 사내 문서 의미 검색용 임베딩 (약 2GB)
  2. PaddleOCR     : 화면 글자 인식 (약 20MB, 최초 사용 시 자동 다운로드)

⚠️ 포터블 원칙
  - 모든 경로는 이 파일 위치 기준 상대경로로 계산한다.
  - 캐시도 프로젝트 폴더 내부(`./models/.cache`)에 둔다.
    (기본값은 사용자 홈 폴더라서 USB 로 옮기면 모델이 따라오지 않는다)

⚠️ 폐쇄망 안내
  사내 PC 는 인터넷이 차단되어 있어 이 스크립트가 실패한다.
  담당자가 **인터넷 되는 PC 에서 먼저 실행**한 뒤,
  `models/` 폴더째로 USB 에 담아 전달해야 한다.

  모델이 없어도 앱은 동작한다:
    - 문서 검색 → 키워드 검색으로 자동 대체
    - 글자 인식 → 사용 불가 안내 후 진행

실행:
    python scripts/download_models.py
    python scripts/download_models.py --check   (다운로드 없이 상태만 확인)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 프로젝트 루트 = 이 파일(scripts/download_models.py) 의 부모의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"

#: 다운로드 캐시도 프로젝트 안에 둔다. (USB 이동 시 함께 따라가도록)
CACHE_DIR = MODELS_DIR / ".cache"

#: 내려받을 임베딩 모델
EMBEDDING_MODEL_ID = "BAAI/bge-m3"
EMBEDDING_DIR = MODELS_DIR / "bge-m3"

#: OCR 모델 저장 위치
OCR_DIR = MODELS_DIR / "omniparser"

#: 모델이 준비된 것으로 판단할 파일 확장자
MODEL_SUFFIXES = (".bin", ".safetensors", ".onnx", ".pdmodel", ".pdiparams")


def has_model_files(directory: Path) -> bool:
    """폴더에 실제 모델 파일이 있는지 확인한다."""
    if not directory.is_dir():
        return False
    return any(
        path.suffix in MODEL_SUFFIXES for path in directory.rglob("*") if path.is_file()
    )


def directory_size_mb(directory: Path) -> float:
    """폴더 크기를 MB 단위로 계산한다."""
    if not directory.is_dir():
        return 0.0
    total = sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
    return total / (1024 * 1024)


def report_status() -> bool:
    """
    모델 준비 상태를 출력한다.

    Returns:
        모든 모델이 준비되었으면 True
    """
    print("-" * 56)
    print("  모델 준비 상태")
    print("-" * 56)

    all_ready = True
    for name, directory in (("문서 검색 (BGE-M3)", EMBEDDING_DIR), ("글자 인식 (OCR)", OCR_DIR)):
        ready = has_model_files(directory)
        all_ready = all_ready and ready
        mark = "준비됨" if ready else "없음"
        size = f" ({directory_size_mb(directory):,.0f} MB)" if ready else ""
        print(f"  [{mark}] {name}{size}")
        print(f"          {directory.relative_to(PROJECT_ROOT)}")

    print("-" * 56)
    if not all_ready:
        print("  ℹ️  모델이 없어도 앱은 동작합니다.")
        print("      - 문서 검색: 키워드 검색으로 자동 대체")
        print("      - 글자 인식: 사용 불가 안내 후 진행")
    return all_ready


def prepare_cache_env() -> None:
    """
    다운로드 캐시를 프로젝트 폴더 안으로 지정한다.

    기본값은 사용자 홈 폴더(~/.cache)라서 USB 로 옮기면 모델이 따라오지 않는다.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(CACHE_DIR)
    os.environ["HUGGINGFACE_HUB_CACHE"] = str(CACHE_DIR)
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(CACHE_DIR)


def download_embedding_model() -> bool:
    """
    BGE-M3 임베딩 모델을 내려받는다.

    Returns:
        성공 여부
    """
    if has_model_files(EMBEDDING_DIR):
        print("  [건너뜀] 문서 검색 모델이 이미 준비되어 있습니다.")
        return True

    print(f"  문서 검색 모델을 내려받습니다: {EMBEDDING_MODEL_ID}")
    print("  (약 2GB, 네트워크 속도에 따라 수 분 걸릴 수 있습니다)")

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("  [!] huggingface_hub 가 설치되어 있지 않습니다.")
        print("      해결: uv sync --extra vision 을 먼저 실행하세요.")
        return False

    try:
        EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=EMBEDDING_MODEL_ID,
            local_dir=str(EMBEDDING_DIR),
            # 큰 파일 중 실제로 필요한 것만 받는다.
            allow_patterns=[
                "*.json",
                "*.txt",
                "*.safetensors",
                "*.model",
                "1_Pooling/*",
            ],
        )
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 안내로 바꾼다
        print(f"  [!] 문서 검색 모델을 내려받지 못했습니다: {exc}")
        print("      인터넷 연결을 확인하세요. (사내망에서는 실패가 정상입니다)")
        return False

    print(f"  [완료] {directory_size_mb(EMBEDDING_DIR):,.0f} MB")
    return True


def download_ocr_model() -> bool:
    """
    PaddleOCR 한국어 모델을 내려받는다.

    PaddleOCR 은 최초 호출 시 모델을 자동으로 받으므로,
    여기서 한 번 호출해 캐시를 프로젝트 안에 채워둔다.

    Returns:
        성공 여부
    """
    if has_model_files(OCR_DIR):
        print("  [건너뜀] 글자 인식 모델이 이미 준비되어 있습니다.")
        return True

    print("  글자 인식(OCR) 모델을 내려받습니다. (약 20MB)")

    try:
        from paddleocr import PaddleOCR
    except ImportError:
        print("  [!] paddleocr 가 설치되어 있지 않습니다.")
        print("      해결: uv sync --extra vision 을 먼저 실행하세요.")
        return False

    try:
        OCR_DIR.mkdir(parents=True, exist_ok=True)
        # PaddleOCR 의 모델 저장 위치를 프로젝트 안으로 지정한다.
        os.environ["PADDLE_OCR_BASE_DIR"] = str(OCR_DIR)
        PaddleOCR(lang="korean", show_log=False)
    except Exception as exc:  # noqa: BLE001
        print(f"  [!] 글자 인식 모델을 내려받지 못했습니다: {exc}")
        print("      인터넷 연결을 확인하세요. (사내망에서는 실패가 정상입니다)")
        return False

    print("  [완료]")
    return True


def main() -> int:
    """진입점."""
    parser = argparse.ArgumentParser(description="PFM-Agent 로컬 모델 다운로드")
    parser.add_argument(
        "--check",
        action="store_true",
        help="다운로드 없이 모델 준비 상태만 확인합니다.",
    )
    args = parser.parse_args()

    print("=" * 56)
    print("  PFM-Agent 로컬 모델 준비")
    print("=" * 56)
    print(f"  저장 위치: {MODELS_DIR}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if args.check:
        report_status()
        return 0

    prepare_cache_env()

    print()
    embedding_ok = download_embedding_model()
    print()
    ocr_ok = download_ocr_model()
    print()

    report_status()

    if not (embedding_ok and ocr_ok):
        print()
        print("  ⚠️  일부 모델을 받지 못했습니다.")
        print("      사내(폐쇄망) PC 라면 정상이며, 앱은 대체 방식으로 동작합니다.")
        print("      정확도를 높이려면 인터넷 되는 PC 에서 이 스크립트를 실행한 뒤")
        print("      models 폴더째 USB 로 옮겨 주세요.")
        # 모델이 없어도 설치를 실패로 처리하지 않는다. (앱은 동작하므로)
        return 0

    print()
    print("  ✅ 모든 모델이 준비되었습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
