"""
동작 확인용 샘플 자료 생성.

사내 실제 자료가 준비되기 전에도 P-Agent 파이프라인 전체를
확인할 수 있도록 예시 문서를 만들고 검색 색인에 추가한다.

⚠️ 생성되는 문서는 **동작 확인용 예시**이며 실제 정책 자료가 아니다.
   (각 문서 안에도 경고 문구가 들어간다)

실행:
    python scripts/create_samples.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def main() -> int:
    """샘플 자료를 만들고 색인에 추가한다."""
    from app.rag.vector_store import VectorStore
    from app.scenarios.na_ion_battery import NA_ION_BATTERY, create_sample_documents

    print("=" * 56)
    print("  P-Agent 동작 확인용 샘플 자료 생성")
    print("=" * 56)

    created = create_sample_documents()
    for path in created:
        print(f"  [생성] {path.relative_to(PROJECT_ROOT)}")

    store = VectorStore(
        data_dir=PROJECT_ROOT / "data",
        model_path=PROJECT_ROOT / "models" / "bge-m3",
    )
    total = 0
    for path in created:
        total += store.add_document(path, relative_to=PROJECT_ROOT)

    print("-" * 56)
    print(f"  검색 색인에 {total}개 조각을 추가했습니다. (방식: {store.method})")
    print()
    print("  이제 P-Agent 에서 아래처럼 요청해 보세요:")
    print(f"    \"{NA_ION_BATTERY.request[:50]}...\"")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
