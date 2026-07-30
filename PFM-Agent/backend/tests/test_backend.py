"""
STEP 4 검증: Backend 골격 + LangGraph 테스트.

실제 MCP 서버 프로세스를 띄운 상태에서 6개 Agent 그래프를 끝까지 실행하고,
FastAPI 엔드포인트가 정상 동작하는지 검증한다.

LLM 은 네트워크 없이 검증하기 위해 가짜(Fake) 클라이언트를 주입한다.

검증 항목:
  - 6개 Agent 가 순서대로 실행되는가
  - Agent 가 MCP 레지스트리를 통해서만 도구를 호출하는가
  - 파이프라인이 실제 산출물(보고서 파일)을 만드는가
  - Kill Switch 가 실행을 중단시키는가
  - 승인 게이트가 위험 도구를 막고, 승인/거절이 반영되는가
  - LLM 실패 시에도 파이프라인이 끝까지 진행되는가 (폐쇄망 대비)
  - API 엔드포인트가 정상 응답하는가
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.agents.graph import AGENT_SEQUENCE, run_graph
from app.agents.run_manager import RunManager
from app.agents.runtime import AgentRuntime, EventBus, current_run_id
from app.agents.state import initial_state
from app.agents.verifier import rule_based_score
from app.config.settings import PROJECT_ROOT, load_settings
from app.llm.base import (
    BaseLLMClient,
    ChatMessage,
    LLMError,
    LLMResponse,
    ToolSpec,
)
from app.mcp_client.client import MCPClient

CONNECT_TIMEOUT = 60.0


# ============================================================
# 가짜 LLM (네트워크 없이 검증)
# ============================================================


class FakeLLM(BaseLLMClient):
    """미리 정해둔 응답을 돌려주는 테스트용 LLM."""

    provider = "fake"

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        super().__init__(model="fake-model")
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self._validate_messages(messages)
        self.calls.append({"system": system, "content": messages[-1].content})

        # 시스템 프롬프트의 키워드로 어느 Agent 가 부른 것인지 구분한다.
        content = ""
        for keyword, response in self.responses.items():
            if system and keyword in system:
                content = response
                break
        return LLMResponse(content=content, model=self.model, finish_reason="end_turn")

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        yield ""

    async def health_check(self) -> tuple[bool, str]:
        return True, "가짜 LLM 정상"


class BrokenLLM(BaseLLMClient):
    """항상 실패하는 LLM. (폐쇄망/키 미설정 상황 재현)"""

    provider = "broken"

    def __init__(self) -> None:
        super().__init__(model="broken-model")

    async def chat(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        raise LLMError("LLM 서버에 연결할 수 없습니다.", provider=self.provider)

    async def stream_chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[str]:
        raise LLMError("LLM 서버에 연결할 수 없습니다.", provider=self.provider)
        yield ""  # pragma: no cover

    async def health_check(self) -> tuple[bool, str]:
        return False, "연결 불가"


DEFAULT_RESPONSES = {
    "계획 수립": '["자료를 수집한다", "보고서를 작성한다"]',
    "검증 담당자": "점수: 80\n사유: 근거 자료가 충분합니다.",
    "보고서를 작성하는 담당자": "## 개요\n\n소듐이온배터리 정책 동향 요약입니다.",
}


# ============================================================
# 픽스처
# ============================================================


@pytest.fixture
async def mcp_client() -> AsyncIterator[MCPClient]:
    """실제 MCP 서버를 기동한 클라이언트."""
    client = MCPClient.from_config(timeout=CONNECT_TIMEOUT)
    async with client:
        yield client


@pytest.fixture
def settings():
    """테스트용 설정 (승인 게이트 활성 상태)."""
    return load_settings()


@pytest.fixture
async def runtime(mcp_client: MCPClient, settings: Any) -> AgentRuntime:
    """가짜 LLM 을 주입한 런타임."""
    return AgentRuntime.create(
        mcp_client,
        settings=settings,
        llm=FakeLLM(DEFAULT_RESPONSES),
        event_bus=EventBus(),
    )


def _cleanup_reports(paths: list[str]) -> None:
    """테스트가 만든 보고서 파일을 정리한다."""
    for path in paths:
        if path:
            (PROJECT_ROOT / path).unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def clean_output_dir() -> AsyncIterator[None]:
    """
    테스트가 `./output` 에 만든 파일을 반드시 정리한다.

    개별 테스트의 정리 호출이 예외로 건너뛰어져도 잔여물이 남지 않도록
    모든 테스트에 자동 적용한다.
    """
    output_dir = PROJECT_ROOT / "output"
    before = set(output_dir.glob("*")) if output_dir.is_dir() else set()

    yield  # type: ignore[misc]

    if output_dir.is_dir():
        for path in output_dir.glob("*"):
            if path not in before and path.is_file():
                path.unlink(missing_ok=True)


# ============================================================
# 1. 그래프 구성
# ============================================================


def test_agent_sequence_has_six_agents() -> None:
    """6개 Agent 가 지정된 순서로 등록되어야 한다."""
    names = [name for name, _ in AGENT_SEQUENCE]
    assert names == [
        "planner",
        "perception",
        "executor",
        "retriever",
        "verifier",
        "generator",
    ]


def test_rule_based_score_bounds() -> None:
    """신뢰도 점수는 0~100 범위를 벗어나지 않아야 한다."""
    assert rule_based_score(0, False) == 20
    assert 0 <= rule_based_score(1, False) <= 100
    assert 0 <= rule_based_score(100, True) <= 100
    # 근거가 많을수록 점수가 높아야 한다.
    assert rule_based_score(3, False) > rule_based_score(1, False)


# ============================================================
# 2. 그래프 전체 실행
# ============================================================


async def test_full_pipeline_produces_report(runtime: AgentRuntime) -> None:
    """
    6개 Agent 파이프라인이 끝까지 실행되어 **실제 Word 보고서**를 만들어야 한다.
    (STEP 8 에서 report 서버가 구현되어 .docx 로 생성된다)
    """
    state = initial_state("test-run-1", "소듐이온배터리 정책동향 보고서를 만들어줘")
    current_run_id.set("test-run-1")
    runtime.register_run("test-run-1")

    result = await run_graph(runtime, state)

    assert result["finished"] is True
    assert result["finish_reason"] == "completed"
    assert result["plan"] == ["자료를 수집한다", "보고서를 작성한다"]
    assert result["confidence"] > 0

    # 실제 파일이 생성되었는지 확인
    report_path = result["report_path"]
    assert report_path, f"보고서가 생성되지 않았습니다. notes={result.get('notes')}"
    full_path = PROJECT_ROOT / report_path
    assert full_path.is_file()

    assert full_path.suffix == ".docx", f"Word 문서가 아닙니다: {full_path.suffix}"

    # 실제 Word 문서로 열리고 내용이 들어 있는지 확인한다.
    from docx import Document

    document = Document(full_path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "소듐이온배터리" in text
    assert "PFM-Agent" in text  # 자동 생성 안내 문구

    _cleanup_reports([report_path])


async def test_pipeline_records_tool_calls(runtime: AgentRuntime) -> None:
    """
    도구 호출이 tool_log 에 기록되어야 한다.
    (프론트엔드 MCP 실행 로그 패널의 데이터 소스)
    """
    state = initial_state("test-run-2", "자료 정리해서 보고서 만들어줘")
    current_run_id.set("test-run-2")
    runtime.register_run("test-run-2")

    result = await run_graph(runtime, state)

    tool_log = result["tool_log"]
    assert tool_log, "도구 호출 기록이 비어 있습니다"

    # 기록 형식 검증
    for entry in tool_log:
        assert set(entry) >= {"step", "tool", "arguments", "ok", "summary"}
        # 표시용 이름은 점 표기여야 한다.
        assert "." in entry["tool"]

    # Generator 가 보고서 생성 도구를 사용했는지 확인
    used_tools = {entry["tool"] for entry in tool_log}
    assert "report.create_word_report" in used_tools

    _cleanup_reports([result.get("report_path", "")])


async def test_pipeline_survives_llm_failure(
    mcp_client: MCPClient, settings: Any
) -> None:
    """
    🔴 폐쇄망 대비: LLM 을 못 써도 파이프라인이 끝까지 진행되고
    최소한의 산출물을 만들어야 한다.
    """
    runtime = AgentRuntime.create(
        mcp_client, settings=settings, llm=BrokenLLM(), event_bus=EventBus()
    )
    state = initial_state("test-run-3", "보고서 작성")
    current_run_id.set("test-run-3")
    runtime.register_run("test-run-3")

    result = await run_graph(runtime, state)

    assert result["finished"] is True
    assert result["finish_reason"] == "completed"  # 오류가 아니라 정상 종료
    assert result["report_path"], "LLM 실패 시에도 보고서가 저장되어야 합니다"

    # LLM 을 못 썼다는 사실이 안내에 남아야 한다.
    notes_text = " ".join(result["notes"])
    assert "LLM" in notes_text

    _cleanup_reports([result["report_path"]])


async def test_unavailable_tools_do_not_break_pipeline(runtime: AgentRuntime) -> None:
    """
    🔴 사용할 수 없는 도구(이 환경에서는 화면 인식)를 만나도
    파이프라인이 중단되지 않고 사유를 기록해야 한다.

    (배포 환경에서 OCR 모델 미설치 등으로 도구가 빠져도 보고서는 나와야 한다)
    """
    state = initial_state("test-run-4", "화면을 보고 자료를 정리해줘")
    current_run_id.set("test-run-4")
    runtime.register_run("test-run-4")

    result = await run_graph(runtime, state)

    assert result["finished"] is True
    assert result["finish_reason"] == "completed"
    assert result["report_path"], "도구를 못 써도 보고서는 생성되어야 합니다"

    # 왜 못 했는지 사유가 남아야 한다.
    notes_text = " ".join(result["notes"]) + " ".join(result["observations"])
    assert any(
        word in notes_text for word in ("화면", "사용할 수 없", "구현되지 않았습니다")
    ), f"사유가 기록되지 않았습니다: {notes_text}"

    _cleanup_reports([result.get("report_path", "")])


# ============================================================
# 3. Kill Switch
# ============================================================


async def test_kill_stops_pipeline(runtime: AgentRuntime) -> None:
    """🔴 안전 검증: Kill Switch 가 파이프라인을 중단시켜야 한다."""
    run_id = "test-kill"
    state = initial_state(run_id, "보고서 만들어줘")
    current_run_id.set(run_id)
    runtime.register_run(run_id)

    # 실행 전에 미리 중단 신호를 넣는다 → 첫 노드에서 즉시 멈춰야 한다.
    runtime.kill(run_id)

    result = await run_graph(runtime, state)

    assert result["finish_reason"] == "killed"
    assert not result.get("report_path"), "중단되었는데 보고서가 생성되었습니다"


async def test_kill_during_run(runtime: AgentRuntime) -> None:
    """
    🔴 안전 검증: 실행 시작 직후 중단하면 실제로 중단되어야 한다.

    (`start()` 는 task 를 만들 뿐 아직 실행하지 않으므로,
     바로 kill 하면 첫 노드에서 확실히 멈춘다 — 타이밍에 의존하지 않는 검증)
    """
    manager = RunManager(runtime)
    record = manager.start("보고서를 만들어줘")

    assert manager.kill(record.run_id) is True

    await record.task
    assert record.status == "killed"
    assert not (record.state or {}).get("report_path"), (
        "중단되었는데 보고서가 생성되었습니다"
    )


async def test_kill_finished_run_is_idempotent(runtime: AgentRuntime) -> None:
    """
    이미 끝난 실행을 중단 요청해도 오류가 아니어야 한다.

    (사용자는 "멈춰줘"라고 했고 이미 멈춰 있으므로 성공으로 처리)
    """
    manager = RunManager(runtime)
    record = manager.start("보고서를 만들어줘")
    await record.task

    assert record.status == "completed"
    assert manager.kill(record.run_id) is True  # 404 가 아니라 성공

    _cleanup_reports([(record.state or {}).get("report_path", "")])


async def test_kill_unknown_run_returns_false(runtime: AgentRuntime) -> None:
    """없는 실행을 중단하려 하면 False 를 반환해야 한다."""
    manager = RunManager(runtime)
    assert manager.kill("존재하지-않는-실행") is False


# ============================================================
# 4. 승인 게이트 (Human-in-the-loop)
# ============================================================


async def test_executor_blocked_without_approval(runtime: AgentRuntime) -> None:
    """
    🔴 안전 검증: 화면 인식이 불가능한 상태에서는
    Executor 가 PC 조작을 시도조차 하지 않아야 한다.
    (엉뚱한 좌표 클릭 방지)
    """
    state = initial_state("test-approval-1", "브라우저를 열고 검색해줘")
    current_run_id.set("test-approval-1")
    runtime.register_run("test-approval-1")

    result = await run_graph(runtime, state)

    executions_text = " ".join(result["executions"])
    assert "화면 상태를 확인할 수 없어" in executions_text

    # automation 도구가 호출되지 않았어야 한다.
    used_tools = {entry["tool"] for entry in result["tool_log"]}
    assert not any(tool.startswith("automation.") for tool in used_tools)

    _cleanup_reports([result.get("report_path", "")])


async def test_approval_request_and_denial(runtime: AgentRuntime) -> None:
    """승인 요청이 발생하고, 거절하면 도구가 실행되지 않아야 한다."""
    run_id = "test-approval-2"
    runtime.register_run(run_id)
    current_run_id.set(run_id)

    # 위험 도구를 직접 호출해 승인 흐름을 검증한다.
    call_task = asyncio.create_task(
        runtime.call_tool("executor", "automation__click", {"x": 1, "y": 2}, run_id=run_id)
    )

    # 승인 요청이 등록될 때까지 대기
    for _ in range(50):
        await asyncio.sleep(0.02)
        if runtime.pending_approvals:
            break

    assert runtime.pending_approvals, "승인 요청이 발생하지 않았습니다"
    approval = runtime.pending_approvals[0]
    assert approval.tool_display == "automation.click"

    # 거절
    assert runtime.resolve_approval(approval.approval_id, False) is True

    result = await call_task
    assert result["ok"] is False
    assert "거절" in result["text"]


async def test_approval_grant_reaches_server(runtime: AgentRuntime) -> None:
    """승인하면 도구 호출이 MCP 서버까지 전달되어야 한다."""
    run_id = "test-approval-3"
    runtime.register_run(run_id)
    current_run_id.set(run_id)

    call_task = asyncio.create_task(
        runtime.call_tool("executor", "automation__click", {"x": 1, "y": 2}, run_id=run_id)
    )

    for _ in range(50):
        await asyncio.sleep(0.02)
        if runtime.pending_approvals:
            break

    approval = runtime.pending_approvals[0]
    assert runtime.resolve_approval(approval.approval_id, True) is True

    result = await call_task
    # 승인 게이트를 통과해 automation 서버까지 도달했는지 확인한다.
    # (이 환경은 화면이 없어 실패하지만, 실패 사유가 '승인 거절'이면 안 된다)
    assert "거절" not in result["text"]


async def test_kill_auto_denies_pending_approval(runtime: AgentRuntime) -> None:
    """🔴 안전 검증: 중단 시 대기 중인 승인 요청도 자동 거절되어야 한다."""
    run_id = "test-approval-4"
    runtime.register_run(run_id)
    current_run_id.set(run_id)

    call_task = asyncio.create_task(
        runtime.call_tool("executor", "automation__click", {"x": 1, "y": 2}, run_id=run_id)
    )

    for _ in range(50):
        await asyncio.sleep(0.02)
        if runtime.pending_approvals:
            break

    runtime.kill(run_id)

    result = await call_task
    assert result["ok"] is False


# ============================================================
# 5. 이벤트 버스 (WebSocket 데이터 소스)
# ============================================================


async def test_events_published_for_each_step(runtime: AgentRuntime) -> None:
    """각 Agent 단계마다 이벤트가 발행되어야 한다."""
    run_id = "test-events"
    state = initial_state(run_id, "보고서 만들어줘")
    current_run_id.set(run_id)
    runtime.register_run(run_id)

    await run_graph(runtime, state)

    events = runtime.event_bus.history(run_id)
    started_steps = {
        event.payload.get("step")
        for event in events
        if event.type == "step_started"
    }
    assert started_steps == {
        "planner",
        "perception",
        "executor",
        "retriever",
        "verifier",
        "generator",
    }

    # 도구 호출 이벤트도 발행되어야 한다.
    assert any(event.type == "tool_call" for event in events)
    assert any(event.type == "tool_result" for event in events)


async def test_event_subscriber_receives_events(runtime: AgentRuntime) -> None:
    """구독자(WebSocket)가 이벤트를 받을 수 있어야 한다."""
    run_id = "test-subscribe"
    runtime.register_run(run_id)

    queue = runtime.event_bus.subscribe(run_id)
    await runtime.emit(run_id, "run_started", user_request="테스트")

    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event.type == "run_started"
    assert event.payload["user_request"] == "테스트"

    runtime.event_bus.unsubscribe(run_id, queue)


# ============================================================
# 6. FastAPI 엔드포인트
# ============================================================


@pytest.fixture
async def api_client(runtime: AgentRuntime) -> AsyncIterator[Any]:
    """
    lifespan 없이 앱을 만들고 런타임을 주입한 테스트 클라이언트.

    (실제 lifespan 은 MCP 서버를 다시 띄우므로, 이미 띄운 런타임을 재사용한다)
    """
    from httpx import ASGITransport, AsyncClient

    from app import main as main_module

    application = main_module.FastAPI(title="PFM-Agent Backend (test)")
    main_module._register_routes(application)

    main_module.app_state.runtime = runtime
    main_module.app_state.run_manager = RunManager(runtime)
    main_module.app_state.mcp_client = runtime.registry.client

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    main_module.app_state.runtime = None
    main_module.app_state.run_manager = None
    main_module.app_state.mcp_client = None


async def test_api_status(api_client: Any) -> None:
    """상태 API 가 도구 목록과 설정을 반환해야 한다."""
    response = await api_client.get("/api/status")
    assert response.status_code == 200

    data = response.json()
    assert data["ready"] is True
    assert len(data["tools"]) == 14
    assert set(data["mcp_servers"]) == {
        "filesystem",
        "screen",
        "automation",
        "rag",
        "report",
    }

    # 승인 필요 도구가 표시되어야 한다.
    approval_tools = [tool for tool in data["tools"] if tool["require_approval"]]
    assert len(approval_tools) == 4


async def test_api_run_and_status(api_client: Any) -> None:
    """실행 시작 → 상태 조회가 동작해야 한다."""
    response = await api_client.post(
        "/api/agent/run", json={"message": "보고서를 만들어줘"}
    )
    assert response.status_code == 200
    run_id = response.json()["run_id"]

    # 실행 완료까지 대기
    report_path = ""
    for _ in range(100):
        await asyncio.sleep(0.1)
        detail = await api_client.get(f"/api/agent/run/{run_id}")
        assert detail.status_code == 200
        data = detail.json()
        if data["status"] != "running":
            report_path = data["report_path"]
            break

    assert data["status"] == "completed", data
    assert data["plan"], "계획이 비어 있습니다"
    assert data["tool_log"], "도구 기록이 비어 있습니다"

    _cleanup_reports([report_path])


async def test_api_run_requires_message(api_client: Any) -> None:
    """빈 요청은 거부되어야 한다."""
    response = await api_client.post("/api/agent/run", json={"message": ""})
    assert response.status_code == 422


async def test_api_kill(api_client: Any) -> None:
    """Kill API 가 실행을 중단해야 한다."""
    response = await api_client.post(
        "/api/agent/run", json={"message": "보고서를 만들어줘"}
    )
    run_id = response.json()["run_id"]

    kill_response = await api_client.post("/api/agent/kill", json={"run_id": run_id})
    assert kill_response.status_code == 200
    assert kill_response.json()["killed"] == [run_id]

    # 종료 대기
    for _ in range(100):
        await asyncio.sleep(0.1)
        detail = await api_client.get(f"/api/agent/run/{run_id}")
        if detail.json()["status"] != "running":
            break

    assert detail.json()["status"] in {"killed", "completed"}
    _cleanup_reports([detail.json().get("report_path", "")])


async def test_api_kill_unknown_run_404(api_client: Any) -> None:
    """없는 실행 중단은 404 와 한글 안내를 반환해야 한다."""
    response = await api_client.post("/api/agent/kill", json={"run_id": "없는실행"})
    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]


async def test_api_approve_unknown_404(api_client: Any) -> None:
    """없는 승인 요청은 404 를 반환해야 한다."""
    response = await api_client.post(
        "/api/agent/approve", json={"approval_id": "없음", "approved": True}
    )
    assert response.status_code == 404


async def test_api_run_not_found(api_client: Any) -> None:
    """없는 실행 조회는 404 를 반환해야 한다."""
    response = await api_client.get("/api/agent/run/없는실행")
    assert response.status_code == 404


async def test_api_root(api_client: Any) -> None:
    """루트 엔드포인트가 서버 정보를 반환해야 한다."""
    response = await api_client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "PFM-Agent Backend"


# ============================================================
# 7. 산출물 위치 (포터블 원칙)
# ============================================================


async def test_report_saved_inside_project(runtime: AgentRuntime) -> None:
    """🔴 포터블 검증: 산출물이 프로젝트 폴더 내부에 저장되어야 한다."""
    state = initial_state("test-output", "보고서 만들어줘")
    current_run_id.set("test-output")
    runtime.register_run("test-output")

    result = await run_graph(runtime, state)
    report_path = result["report_path"]
    assert report_path

    full_path = (PROJECT_ROOT / report_path).resolve()
    assert full_path.is_relative_to(PROJECT_ROOT.resolve())
    assert Path(report_path).parts[0] == "output"

    _cleanup_reports([report_path])


# ============================================================
# 8. 안전장치 통합 (STEP 5)
# ============================================================


async def test_file_write_is_undoable(runtime: AgentRuntime) -> None:
    """
    🔴 되돌리기 통합: 에이전트가 저장한 파일을 되돌리면
    파일이 삭제(신규) 또는 이전 내용으로 복원되어야 한다.
    """
    run_id = "test-undo"
    runtime.register_run(run_id)
    current_run_id.set(run_id)
    runtime.undo_manager.clear()

    rel_path = "./data/_undo_test.md"
    target = PROJECT_ROOT / "data" / "_undo_test.md"
    target.unlink(missing_ok=True)

    # 1) 신규 파일 저장 → 되돌리면 삭제되어야 한다.
    result = await runtime.call_tool(
        "generator",
        "filesystem__write_file",
        {"path": rel_path, "content": "첫 번째 내용"},
        run_id=run_id,
    )
    assert result["ok"] is True
    assert target.is_file()
    assert runtime.undo_manager.can_undo is True

    description = await runtime.undo_last(run_id)
    assert "파일 생성" in description
    assert not target.exists(), "되돌렸는데 파일이 남아 있습니다"

    # 2) 기존 파일 수정 → 되돌리면 이전 내용이 복원되어야 한다.
    target.write_text("원래 내용", encoding="utf-8")
    await runtime.call_tool(
        "generator",
        "filesystem__write_file",
        {"path": rel_path, "content": "덮어쓴 내용"},
        run_id=run_id,
    )
    assert target.read_text(encoding="utf-8") == "덮어쓴 내용"

    await runtime.undo_last(run_id)
    assert target.read_text(encoding="utf-8") == "원래 내용"

    target.unlink(missing_ok=True)


async def test_dangerous_tools_are_not_undoable(runtime: AgentRuntime) -> None:
    """
    🔴 마우스/키보드 조작은 되돌릴 수 없으므로 스택에 쌓이지 않아야 한다.
    ("되돌릴 수 있다"는 잘못된 안내를 막기 위함)
    """
    run_id = "test-undo-2"
    runtime.register_run(run_id)
    current_run_id.set(run_id)
    runtime.undo_manager.clear()

    # 승인 게이트를 통과시키고 automation 도구를 호출한다.
    async def approve(tool: Any, arguments: dict[str, Any]) -> bool:
        return True

    runtime.registry.approval_callback = approve
    await runtime.call_tool(
        "executor", "automation__click", {"x": 1, "y": 2}, run_id=run_id
    )

    assert runtime.undo_manager.can_undo is False


async def test_tool_calls_written_to_action_log(
    runtime: AgentRuntime, tmp_path: Path
) -> None:
    """모든 도구 호출이 actions.jsonl 에 기록되어야 한다."""
    from app.safety.action_logger import ActionLogger

    # 테스트용 임시 로그 파일로 교체
    runtime.action_logger = ActionLogger(tmp_path / "actions.jsonl")

    run_id = "test-log"
    runtime.register_run(run_id)
    current_run_id.set(run_id)

    await runtime.call_tool(
        "retriever", "filesystem__list_dir", {"path": "."}, run_id=run_id
    )

    records = runtime.action_logger.read_run(run_id)
    assert len(records) == 1
    assert records[0]["tool"] == "filesystem.list_dir"
    assert records[0]["step"] == "retriever"
    assert records[0]["ok"] is True


async def test_api_undo_and_actions(api_client: Any, runtime: AgentRuntime) -> None:
    """되돌리기 / 액션 조회 API 가 동작해야 한다."""
    runtime.undo_manager.clear()

    # 되돌릴 것이 없으면 400 + 한글 안내
    response = await api_client.post("/api/agent/undo", json={})
    assert response.status_code == 400
    assert "되돌릴 작업이 없습니다" in response.json()["detail"]

    # 파일을 저장한 뒤 되돌리기
    run_id = "test-api-undo"
    runtime.register_run(run_id)
    current_run_id.set(run_id)
    target = PROJECT_ROOT / "data" / "_api_undo_test.md"
    target.unlink(missing_ok=True)

    await runtime.call_tool(
        "generator",
        "filesystem__write_file",
        {"path": "./data/_api_undo_test.md", "content": "내용"},
        run_id=run_id,
    )
    assert target.is_file()

    response = await api_client.post("/api/agent/undo", json={"run_id": run_id})
    assert response.status_code == 200
    assert "파일 생성" in response.json()["undone"]
    assert not target.exists()

    # 액션 기록 조회
    actions = await api_client.get("/api/agent/actions")
    assert actions.status_code == 200
    assert actions.json()["count"] >= 1


async def test_api_status_reports_safety(api_client: Any) -> None:
    """상태 API 가 안전장치 상태를 보고해야 한다."""
    response = await api_client.get("/api/status")
    data = response.json()

    assert "kill_switch" in data
    assert data["kill_switch"]["key"] == "esc"
    assert isinstance(data["kill_switch"]["global_hook_available"], bool)
    assert data["require_approval"] is True
    assert "can_undo" in data
