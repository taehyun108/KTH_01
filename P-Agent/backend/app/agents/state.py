"""
LangGraph 공유 상태 정의.

6개 Agent(Planner/Perception/Executor/Retriever/Verifier/Generator)가
이 상태 객체를 순서대로 갱신하며 작업을 진행한다.

설계 원칙
---------
- 각 Agent 는 자기 담당 필드만 갱신한다. (다른 Agent 결과를 덮어쓰지 않음)
- 도구 호출 기록은 `tool_log` 에 누적해 프론트엔드가 실시간 표시한다.
- 아직 구현되지 않은 도구(STEP 6~8 스텁)를 만나도 그래프는 멈추지 않고
  `notes` 에 사유를 남기고 다음 단계로 진행한다.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

#: 각 Agent 단계 이름
AgentStep = Literal[
    "planner", "perception", "executor", "retriever", "verifier", "generator"
]

#: 실행 종료 사유
FinishReason = Literal["completed", "killed", "error", ""]


class ToolLogEntry(TypedDict):
    """도구 호출 기록 한 건. (프론트엔드 MCP 로그 패널에 표시)"""

    step: str
    """호출한 Agent 단계"""

    tool: str
    """표시용 도구 이름 (예: filesystem.read_file)"""

    arguments: dict[str, Any]
    ok: bool
    summary: str
    """결과 요약 (길면 잘라서 저장)"""


class Evidence(TypedDict):
    """Retriever 가 수집한 근거 자료 한 건."""

    source: str
    """출처 (파일 경로 / URL / 사내 문서 ID)"""

    content: str
    origin: str
    """수집 경로 ("rag" | "web" | "file")"""


class AgentState(TypedDict, total=False):
    """
    LangGraph 전역 상태.

    `total=False` 이므로 각 노드는 갱신할 필드만 반환하면 된다.
    """

    # --- 입력 ---
    run_id: str
    """실행 식별자 (WebSocket 이벤트 및 승인 요청에 사용)"""

    user_request: str
    """사용자가 자연어로 입력한 요청"""

    # --- Planner ---
    plan: list[str]
    """실행 계획 (단계별 한 줄 설명)"""

    # --- Perception ---
    observations: list[str]
    """화면 인식 결과"""

    # --- Executor ---
    executions: list[str]
    """PC 조작 수행 결과"""

    # --- Retriever ---
    evidences: list[Evidence]
    """수집한 근거 자료"""

    # --- Verifier ---
    confidence: int
    """신뢰도 점수 (0~100)"""

    verification: str
    """검증 결과 설명"""

    # --- Generator ---
    report_path: str
    """생성된 보고서 파일 경로 (프로젝트 폴더 기준 상대경로)"""

    summary: str
    """사용자에게 보여줄 최종 요약"""

    # --- 공통 (여러 노드가 누적) ---
    tool_log: Annotated[list[ToolLogEntry], operator.add]
    """도구 호출 기록 (노드별 결과가 합쳐짐)"""

    notes: Annotated[list[str], operator.add]
    """진행 중 특이사항 (미구현 도구 안내 등)"""

    # --- 제어 ---
    finished: bool
    finish_reason: FinishReason
    error: str


def initial_state(run_id: str, user_request: str) -> AgentState:
    """새 실행을 위한 초기 상태를 만든다."""
    return AgentState(
        run_id=run_id,
        user_request=user_request,
        plan=[],
        observations=[],
        executions=[],
        evidences=[],
        confidence=0,
        verification="",
        report_path="",
        summary="",
        tool_log=[],
        notes=[],
        finished=False,
        finish_reason="",
        error="",
    )
