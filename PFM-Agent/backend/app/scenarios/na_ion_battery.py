"""
시나리오: 소듐이온배터리 정책동향 보고서.

PFM-Agent 의 대표 사용 사례를 미리 정의해 둔 것이다.
사용자가 매번 긴 요청을 입력하지 않아도 되고,
데모/검증 시 동일한 조건으로 재현할 수 있다.

사용처
------
1. 프론트엔드 "예시 요청" 버튼
2. 배포 후 동작 확인 (샘플 자료로 보고서가 나오는지)

샘플 자료
---------
`./data/samples/` 에 예시 문서를 만들어 RAG 색인에 넣을 수 있다.
사내 실제 자료가 준비되기 전에도 파이프라인 전체를 확인할 수 있게 하기 위함이다.
⚠️ 샘플 자료는 **동작 확인용 예시**이며 실제 정책 내용이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

#: 이 파일: <루트>/backend/app/scenarios/na_ion_battery.py
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

#: 샘플 자료 폴더
SAMPLE_DIR: Path = PROJECT_ROOT / "data" / "samples"


@dataclass(frozen=True)
class Scenario:
    """미리 정의된 사용 시나리오."""

    key: str
    title: str
    request: str
    """에이전트에 전달할 자연어 요청"""

    description: str
    expected_outputs: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        """API 응답용 dict."""
        return {
            "key": self.key,
            "title": self.title,
            "request": self.request,
            "description": self.description,
            "expected_outputs": list(self.expected_outputs),
        }


#: 소듐이온배터리 정책동향 보고서 시나리오
NA_ION_BATTERY = Scenario(
    key="na_ion_battery",
    title="소듐이온배터리 정책동향 보고서",
    request=(
        "소듐이온배터리 관련 국내외 정책 동향을 조사해서 "
        "정부 부처 대응용 보고서를 작성해줘. "
        "개요, 주요 내용, 시사점 순서로 정리하고 출처를 반드시 표기해줘."
    ),
    description=(
        "사내 자료와 로컬 문서에서 소듐이온배터리 정책 관련 근거를 수집하고, "
        "신뢰도를 검증한 뒤 Word 보고서를 생성합니다."
    ),
    expected_outputs=("output/*.docx",),
)

#: 등록된 시나리오 목록
SCENARIOS: dict[str, Scenario] = {NA_ION_BATTERY.key: NA_ION_BATTERY}


# ============================================================
# 샘플 자료 (동작 확인용)
# ============================================================

#: ⚠️ 아래 내용은 파이프라인 동작 확인을 위한 **예시**이며 실제 정책 자료가 아니다.
SAMPLE_DOCUMENTS: dict[str, str] = {
    "소듐이온배터리_기술개요.md": """# 소듐이온배터리 기술 개요

> ⚠️ 본 문서는 PFM-Agent 동작 확인용 예시 자료입니다. 실제 정책 자료가 아닙니다.

## 기술 특성

소듐이온배터리는 리튬 대신 소듐(나트륨)을 전하 운반체로 사용하는 이차전지다.
소듐은 리튬보다 지각 내 매장량이 훨씬 많아 원료 수급이 안정적이다.

## 장단점

- 장점: 원료 가격이 낮고 수급이 안정적이며, 저온 성능이 상대적으로 우수하다.
- 단점: 에너지 밀도가 리튬이온 대비 낮아 전기차보다 ESS 에 적합하다.

## 응용 분야

에너지저장장치(ESS), 전력망 안정화, 저속 전기차 등이 주요 응용 분야로 거론된다.
""",
    "소듐이온배터리_시장동향.md": """# 소듐이온배터리 시장 동향

> ⚠️ 본 문서는 PFM-Agent 동작 확인용 예시 자료입니다. 실제 수치가 아닙니다.

## 시장 개요

ESS 수요 증가와 리튬 가격 변동성 확대에 따라 소듐이온배터리에 대한
관심이 높아지고 있다. 다만 상용화 초기 단계로 양산 규모는 제한적이다.

## 주요 동향

- 중국 업체들이 양산 라인 구축을 선도하고 있다.
- 국내에서는 소재·셀 단계의 연구개발이 진행 중이다.
- 리튬 가격이 안정되면 경쟁력이 약화될 수 있다는 분석도 있다.

## 과제

에너지 밀도 개선과 양산 원가 절감이 상용화의 핵심 과제로 지목된다.
""",
    "이차전지_정책_참고.md": """# 이차전지 관련 정책 참고 자료

> ⚠️ 본 문서는 PFM-Agent 동작 확인용 예시 자료입니다. 실제 정책 내용이 아닙니다.

## 정책 방향

정부는 이차전지를 국가전략기술로 분류하고 연구개발 및 설비투자에 대한
세제 지원을 운영하고 있다. 차세대 전지 기술도 지원 대상에 포함된다.

## 지원 수단

- 국가전략기술 연구개발비 세액공제
- 설비투자 세액공제
- 소재·부품·장비 국산화 지원 사업

## 대응 시 고려사항

소듐이온배터리는 차세대 전지로 분류될 수 있어 지원 대상 해당 여부를
사전에 확인할 필요가 있다.
""",
}


def create_sample_documents(target_dir: Path | None = None) -> list[Path]:
    """
    샘플 자료를 파일로 만든다.

    사내 실제 자료가 준비되기 전에도 파이프라인을 확인할 수 있게 한다.

    Args:
        target_dir: 저장할 폴더 (생략 시 ./data/samples)

    Returns:
        생성된 파일 경로 목록
    """
    directory = target_dir or SAMPLE_DIR
    directory.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    for name, content in SAMPLE_DOCUMENTS.items():
        path = directory / name
        path.write_text(content, encoding="utf-8")
        created.append(path)

    return created


def get_scenario(key: str) -> Scenario | None:
    """키로 시나리오를 조회한다."""
    return SCENARIOS.get(key)


def list_scenarios() -> list[dict[str, object]]:
    """등록된 시나리오 목록을 반환한다. (API/UI 용)"""
    return [scenario.to_dict() for scenario in SCENARIOS.values()]
