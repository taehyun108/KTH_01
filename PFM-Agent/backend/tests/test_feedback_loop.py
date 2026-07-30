"""
피드백 루프 검증 (Verifier → Retriever 재검색).

검증 항목
---------
1. 재검색 판단 순수 함수 (`app.agents.feedback`)
2. 그래프에 되돌아가기 엣지가 실제로 존재하는가
3. 신뢰도가 낮으면 정말 재검색이 일어나는가 (실제 MCP 서버 + 그래프 실행)
4. 신뢰도가 높으면 재검색하지 않는가
5. **무한 루프가 발생하지 않는가** — 이 파일의 가장 중요한 검증
6. 재검색이 이전 근거를 버리지 않는가 (누적)
7. LLM 이 죽어도 피드백 루프가 동작하는가 (폐쇄망 대비)

LLM 은 네트워크 없이 검증하기 위해 가짜(Fake) 클라이언트를 주입한다.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agents.feedback import (
    evidence_key,
    extract_keywords,
    fallback_queries,
    merge_evidences,
    normalize_query,
    parse_query_response,
    select_new_queries,
    should_retry,
    strip_particle,
)
from app.agents.graph import (
    RETRY_SOURCE,
    RETRY_TARGET,
    recursion_limit_for,
    run_graph,
)
from app.agents.retriever import resolve_queries
from app.agents.runtime import AgentRuntime, EventBus
from app.agents.state import AgentState, Evidence, initial_state
from app.config.settings import MAX_AGENT_ITERATIONS, PROJECT_ROOT, load_settings
from app.llm.base import BaseLLMClient, ChatMessage, LLMError, LLMResponse, ToolSpec
from app.mcp_client.client import MCPClient

CONNECT_TIMEOUT = 60.0

#: 테스트에 사용할 요청문
REQUEST = "소듐이온배터리 최근 정책동향을 조사해서 보고서로 만들어줘"


# ============================================================
# 가짜 LLM
# ============================================================


class ScriptedLLM(BaseLLMClient):
    """
    시스템 프롬프트의 키워드로 응답을 고르는 테스트용 LLM.

    검색어 제안은 **호출마다 다른 값**을 돌려주어 여러 회차 재검색을
    재현할 수 있게 한다.
    """

    provider = "scripted"

    def __init__(self, score: int) -> None:
        super().__init__(model="scripted-model")
        self.score = score
        self.query_calls = 0
        self.verify_calls = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self._validate_messages(messages)
        system = system or ""
        content = ""

        if "검색어 제안 담당자" in system:
            self.query_calls += 1
            n = self.query_calls
            content = f'["대체검색어{n}A", "대체검색어{n}B"]'
        elif "검증 담당자" in system:
            self.verify_calls += 1
            content = f"점수: {self.score}\n사유: 테스트용 고정 점수입니다."
        elif "계획 수립" in system:
            content = '["자료를 수집한다", "보고서를 작성한다"]'
        elif "보고서를 작성하는 담당자" in system:
            content = "## 개요\n\n테스트 본문입니다."

        return LLMResponse(content=content, model=self.model, finish_reason="end_turn")

    async def stream_chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[str]:
        yield ""

    async def health_check(self) -> tuple[bool, str]:
        return True, "가짜 LLM 정상"


class DeadLLM(BaseLLMClient):
    """항상 실패하는 LLM. (폐쇄망 / 키 미설정 재현)"""

    provider = "dead"

    def __init__(self) -> None:
        super().__init__(model="dead-model")

    async def chat(self, messages: list[ChatMessage], **kwargs: Any) -> LLMResponse:
        raise LLMError("LLM 서버에 연결할 수 없습니다.", provider=self.provider)

    async def stream_chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[str]:
        raise LLMError("LLM 서버에 연결할 수 없습니다.", provider=self.provider)
        yield ""  # pragma: no cover

    async def health_check(self) -> tuple[bool, str]:
        return False, "연결 불가"


# ============================================================
# 픽스처
# ============================================================


@pytest.fixture
async def mcp_client() -> AsyncIterator[MCPClient]:
    """실제 MCP 서버를 기동한 클라이언트."""
    client = MCPClient.from_config(timeout=CONNECT_TIMEOUT)
    async with client:
        yield client


def _make_runtime(
    mcp_client: MCPClient,
    llm: BaseLLMClient,
    *,
    max_iterations: int = 2,
    threshold: int = 50,
) -> AgentRuntime:
    """재검색 설정을 지정한 런타임을 만든다."""
    settings = dataclasses.replace(
        load_settings(),
        agent_max_iterations=max_iterations,
        agent_confidence_threshold=threshold,
    )
    return AgentRuntime.create(
        mcp_client, settings=settings, llm=llm, event_bus=EventBus()
    )


@pytest.fixture(autouse=True)
def clean_output_dir() -> AsyncIterator[None]:
    """테스트가 `./output` 에 만든 파일을 정리한다."""
    output_dir = PROJECT_ROOT / "output"
    before = set(output_dir.glob("*")) if output_dir.is_dir() else set()

    yield  # type: ignore[misc]

    if output_dir.is_dir():
        for path in output_dir.glob("*"):
            if path not in before and path.is_file():
                path.unlink(missing_ok=True)


async def _run(
    runtime: AgentRuntime, *, max_iterations: int, request: str = REQUEST
) -> AgentState:
    """그래프를 한 번 끝까지 실행한다."""
    state = initial_state("t-feedback", request, max_iterations=max_iterations)
    return await run_graph(runtime, state)


# ============================================================
# 1. 순수 함수 — 검색어 만들기
# ============================================================


def test_normalize_query_collapses_whitespace() -> None:
    """공백만 다른 검색어는 같은 것으로 봐야 한다."""
    assert normalize_query("  소듐이온배터리   정책 ") == normalize_query(
        "소듐이온배터리 정책"
    )


def test_strip_particle_removes_korean_particles() -> None:
    """한국어 조사가 붙은 단어에서 조사를 떼어내야 한다."""
    assert strip_particle("정책동향을") == "정책동향"
    assert strip_particle("배터리에서") == "배터리"
    assert strip_particle("보고서의") == "보고서"


def test_strip_particle_keeps_short_words() -> None:
    """짧은 단어는 조사처럼 보여도 건드리지 않는다. (어간 훼손 방지)"""
    assert strip_particle("도가") == "도가"
    assert strip_particle("의") == "의"


def test_extract_keywords_drops_instruction_verbs() -> None:
    """지시 동사('조사해서', '만들어줘')는 검색어에서 빠져야 한다."""
    words = extract_keywords(REQUEST)
    assert "소듐이온배터리" in words
    assert "정책동향" in words
    # 지시 표현 / 불용어는 제외
    assert not any("조사" in word for word in words)
    assert not any("보고서" in word for word in words)
    assert "최근" not in words


def test_fallback_queries_broaden_progressively() -> None:
    """LLM 없이도 범위를 넓혀 가는 대체 검색어를 만들어야 한다."""
    queries = fallback_queries(REQUEST)
    assert queries, "대체 검색어가 하나도 없으면 재검색을 할 수 없다"
    # 원문보다 짧아야(=넓어야) 의미가 있다.
    assert all(len(query) < len(REQUEST) for query in queries)
    # 가장 긴 핵심 단어가 후보에 포함되어야 한다.
    assert any("소듐이온배터리" in query for query in queries)
    # 중복이 없어야 한다.
    assert len({normalize_query(q) for q in queries}) == len(queries)


def test_fallback_queries_handles_empty_request() -> None:
    """의미 있는 단어가 없으면 빈 목록을 반환해야 한다. (재검색 안 함)"""
    assert fallback_queries("") == []
    assert fallback_queries("!!! ???") == []


def test_parse_query_response_accepts_json_array() -> None:
    """LLM 이 JSON 배열로 답하면 그대로 파싱한다."""
    assert parse_query_response('["검색어1", "검색어2"]') == ["검색어1", "검색어2"]


def test_parse_query_response_recovers_from_markdown() -> None:
    """코드블록·목록 기호가 섞여 와도 복구해야 한다."""
    assert parse_query_response('```json\n["가", "나"]\n```') == ["가", "나"]
    assert parse_query_response("- 첫째\n- 둘째") == ["첫째", "둘째"]
    assert parse_query_response('1. "하나"\n2. "둘"') == ["하나", "둘"]


def test_select_new_queries_skips_tried() -> None:
    """이미 시도한 검색어는 다시 고르지 않는다. (안전장치 2)"""
    selected = select_new_queries(["가", "나", "다"], ["나"])
    assert selected == ["가", "다"]


def test_select_new_queries_is_case_and_space_insensitive() -> None:
    """대소문자·공백만 다른 검색어도 '이미 시도한 것'으로 본다."""
    assert select_new_queries(["Sodium  Battery"], ["sodium battery"]) == []


def test_select_new_queries_respects_limit() -> None:
    """제안 개수 상한을 지켜야 한다."""
    assert len(select_new_queries(["가", "나", "다", "라"], [], limit=2)) == 2


# ============================================================
# 2. 순수 함수 — 재검색 판단 / 근거 누적
# ============================================================


def test_should_retry_when_below_threshold() -> None:
    """기준치 미만이고 회차가 남아 있으면 재검색한다."""
    assert should_retry(confidence=20, threshold=50, iteration=1, max_iterations=2)


def test_should_retry_false_when_confident() -> None:
    """기준치 이상이면 재검색하지 않는다."""
    assert not should_retry(confidence=80, threshold=50, iteration=1, max_iterations=2)
    # 경계값: 기준치와 같으면 통과로 본다.
    assert not should_retry(confidence=50, threshold=50, iteration=1, max_iterations=2)


def test_should_retry_false_at_iteration_cap() -> None:
    """회차를 다 쓰면 점수가 낮아도 재검색하지 않는다. (안전장치 1)"""
    assert not should_retry(confidence=0, threshold=50, iteration=2, max_iterations=2)
    assert not should_retry(confidence=0, threshold=50, iteration=9, max_iterations=2)


def test_should_retry_disabled_by_single_iteration() -> None:
    """max_iterations=1 은 피드백 루프 비활성(기존 단방향 동작)이어야 한다."""
    assert not should_retry(confidence=0, threshold=50, iteration=1, max_iterations=1)


def test_merge_evidences_accumulates_and_dedups() -> None:
    """재검색 결과는 기존 근거에 누적되고, 같은 자료는 한 번만 남아야 한다."""
    old = [Evidence(source="a.md", content="내용 A", origin="rag")]
    new = [
        Evidence(source="a.md", content="내용 A", origin="rag"),  # 중복
        Evidence(source="b.md", content="내용 B", origin="rag"),
    ]
    merged = merge_evidences(old, new)
    assert [item["source"] for item in merged] == ["a.md", "b.md"]


def test_evidence_key_ignores_whitespace_differences() -> None:
    """줄바꿈·공백만 다른 같은 문서는 중복으로 판단해야 한다."""
    a = Evidence(source="a.md", content="내용   A", origin="rag")
    b = Evidence(source="a.md", content="내용\nA", origin="rag")
    assert evidence_key(a) == evidence_key(b)


# ============================================================
# 3. 그래프 구조
# ============================================================


def test_graph_has_retry_edge() -> None:
    """Verifier 에서 Retriever 로 되돌아가는 엣지가 실제로 있어야 한다."""
    assert RETRY_SOURCE == "verifier"
    assert RETRY_TARGET == "retriever"


def test_recursion_limit_grows_with_iterations() -> None:
    """회차가 늘면 recursion_limit 도 늘어야 한다. (GraphRecursionError 방지)"""
    assert recursion_limit_for(1) < recursion_limit_for(2) < recursion_limit_for(5)
    # 회차를 다 써도 노드 방문 수보다 여유가 있어야 한다.
    assert recursion_limit_for(MAX_AGENT_ITERATIONS) > 6 + (MAX_AGENT_ITERATIONS - 1) * 3


def test_resolve_queries_defaults_to_user_request() -> None:
    """첫 회차에는 사용자 요청문을 그대로 검색어로 쓴다."""
    state = initial_state("t", REQUEST)
    assert resolve_queries(state) == [REQUEST]


def test_resolve_queries_uses_retry_queries() -> None:
    """재검색 회차에는 Verifier 가 제안한 검색어를 쓴다."""
    state = initial_state("t", REQUEST)
    state["search_queries"] = ["대체어1", "대체어2"]
    assert resolve_queries(state) == ["대체어1", "대체어2"]


def test_resolve_queries_ignores_blank_entries() -> None:
    """빈 문자열만 들어오면 요청문으로 되돌아가야 한다."""
    state = initial_state("t", REQUEST)
    state["search_queries"] = ["", "   "]
    assert resolve_queries(state) == [REQUEST]


# ============================================================
# 4. 실제 그래프 실행 — 재검색이 일어나는가
# ============================================================


async def test_low_confidence_triggers_retry(mcp_client: MCPClient) -> None:
    """신뢰도가 낮으면 Retriever 로 되돌아가 다시 검색해야 한다."""
    llm = ScriptedLLM(score=10)
    runtime = _make_runtime(mcp_client, llm, max_iterations=2)

    result = await _run(runtime, max_iterations=2)

    assert result["iteration"] == 2, "재검색이 일어나지 않았다"
    assert llm.query_calls >= 1, "대체 검색어를 요청하지 않았다"
    # 검색어가 2회 이상 시도되어야 한다. (원문 + 대체어)
    assert len(result["tried_queries"]) >= 2
    assert REQUEST in result["tried_queries"]
    # 재검색 사유가 사용자 안내에 남아야 한다.
    assert any("재검색" in note for note in result["notes"])
    # 재검색을 했더라도 보고서는 끝까지 만들어져야 한다.
    assert result["report_path"], "재검색 후 보고서가 생성되지 않았다"
    assert result["finish_reason"] == "completed"


async def test_high_confidence_skips_retry(mcp_client: MCPClient) -> None:
    """신뢰도가 충분하면 재검색 없이 곧바로 보고서를 만들어야 한다."""
    llm = ScriptedLLM(score=95)
    runtime = _make_runtime(mcp_client, llm, max_iterations=2)

    result = await _run(runtime, max_iterations=2)

    assert result["iteration"] == 1, "불필요한 재검색이 일어났다"
    assert llm.query_calls == 0, "대체 검색어를 만들 필요가 없었다"
    assert len(result["tried_queries"]) == 1
    assert result["report_path"]


async def test_retry_disabled_by_setting(mcp_client: MCPClient) -> None:
    """AGENT_MAX_ITERATIONS=1 이면 점수가 낮아도 재검색하지 않아야 한다."""
    llm = ScriptedLLM(score=0)
    runtime = _make_runtime(mcp_client, llm, max_iterations=1)

    result = await _run(runtime, max_iterations=1)

    assert result["iteration"] == 1
    assert llm.query_calls == 0
    assert result["report_path"]


# ============================================================
# 5. ★ 무한 루프 방지 (가장 중요)
# ============================================================


async def test_always_low_score_terminates(mcp_client: MCPClient) -> None:
    """
    점수가 **항상** 기준치 미만이어도 실행은 반드시 끝나야 한다.

    피드백 루프를 넣을 때 가장 위험한 실패 모드(무한 루프)를 직접 검증한다.
    """
    llm = ScriptedLLM(score=0)
    runtime = _make_runtime(mcp_client, llm, max_iterations=MAX_AGENT_ITERATIONS)

    result = await _run(runtime, max_iterations=MAX_AGENT_ITERATIONS)

    # 회차 상한을 넘지 않아야 한다.
    assert 1 <= result["iteration"] <= MAX_AGENT_ITERATIONS
    # 종료 상태여야 한다.
    assert result["finished"] is True
    assert result["finish_reason"] == "completed"
    # 루프 플래그가 소비(초기화)된 상태로 끝나야 한다.
    assert result["retry_reason"] == ""
    # 보고서는 신뢰도가 낮아도 만들어진다. (경고와 함께)
    assert result["report_path"]


async def test_retry_never_repeats_a_query(mcp_client: MCPClient) -> None:
    """같은 검색어를 두 번 시도하지 않아야 한다. (안전장치 2)"""
    llm = ScriptedLLM(score=0)
    runtime = _make_runtime(mcp_client, llm, max_iterations=MAX_AGENT_ITERATIONS)

    result = await _run(runtime, max_iterations=MAX_AGENT_ITERATIONS)

    tried = [normalize_query(item) for item in result["tried_queries"]]
    assert len(tried) == len(set(tried)), f"검색어가 중복 시도되었다: {tried}"


async def test_low_confidence_warning_reaches_user(mcp_client: MCPClient) -> None:
    """재검색해도 신뢰도가 낮으면 사람이 검토하라는 안내가 남아야 한다."""
    llm = ScriptedLLM(score=0)
    runtime = _make_runtime(mcp_client, llm, max_iterations=2)

    result = await _run(runtime, max_iterations=2)

    assert any("사람이 검토" in note for note in result["notes"])


# ============================================================
# 6. 근거 누적 / 이벤트
# ============================================================


async def test_retry_does_not_lose_previous_evidence(mcp_client: MCPClient) -> None:
    """재검색이 이전 회차에서 찾은 근거를 지워서는 안 된다."""
    llm = ScriptedLLM(score=10)
    runtime = _make_runtime(mcp_client, llm, max_iterations=2)

    # 1회차에서 근거를 확보한 상태를 만들어 둔다.
    state = initial_state("t-keep", REQUEST, max_iterations=2)
    state["evidences"] = [
        Evidence(source="미리있던자료.md", content="1회차에서 찾은 내용", origin="rag")
    ]

    result = await run_graph(runtime, state)

    sources = [item["source"] for item in result["evidences"]]
    assert "미리있던자료.md" in sources, "재검색이 기존 근거를 덮어썼다"


async def test_retry_emits_event(mcp_client: MCPClient) -> None:
    """재검색이 시작되면 프론트엔드가 알 수 있도록 이벤트를 보내야 한다."""
    llm = ScriptedLLM(score=10)
    runtime = _make_runtime(mcp_client, llm, max_iterations=2)

    run_id = "t-retry-event"
    state = initial_state(run_id, REQUEST, max_iterations=2)
    runtime.register_run(run_id)

    await run_graph(runtime, state)

    events = runtime.event_bus.history(run_id)
    retry_events = [e for e in events if e.type == "retry_requested"]
    assert retry_events, "retry_requested 이벤트가 발생하지 않았다"

    payload = retry_events[0].payload
    assert payload["iteration"] == 2
    assert payload["queries"], "이벤트에 검색어가 담겨야 한다"
    assert payload["confidence"] < 50

    # Retriever 가 두 번 실행됐다는 사실도 이벤트로 확인할 수 있어야 한다.
    retriever_starts = [
        e
        for e in events
        if e.type == "step_started" and e.payload.get("step") == "retriever"
    ]
    assert len(retriever_starts) == 2, "Retriever 가 재실행되지 않았다"
    assert retriever_starts[1].payload["iteration"] == 2


# ============================================================
# 7. LLM 장애 시에도 루프가 동작하는가 (폐쇄망 대비)
# ============================================================


async def test_feedback_loop_works_without_llm(mcp_client: MCPClient) -> None:
    """
    LLM 이 죽어도 규칙 기반 대체 검색어로 재검색이 동작해야 한다.

    폐쇄망에서 P-GPT 가 응답하지 않는 상황을 재현한다.
    """
    runtime = _make_runtime(mcp_client, DeadLLM(), max_iterations=2)

    result = await _run(runtime, max_iterations=2)

    # LLM 없이도 재검색이 일어났어야 한다. (규칙 기반 검색어)
    assert result["iteration"] == 2, "LLM 없이는 재검색이 되지 않았다"
    assert len(result["tried_queries"]) >= 2
    # 그래도 끝까지 진행되어야 한다.
    assert result["finished"] is True
    assert result["report_path"]


# ============================================================
# 8. 설정값 안전장치
# ============================================================


def test_settings_clamp_max_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` 에 과한 값을 넣어도 하드 상한으로 잘려야 한다."""
    from app.config import settings as settings_module

    monkeypatch.setattr(
        settings_module, "_read_env", lambda: {"AGENT_MAX_ITERATIONS": "999"}
    )
    assert settings_module.load_settings().agent_max_iterations == MAX_AGENT_ITERATIONS

    monkeypatch.setattr(
        settings_module, "_read_env", lambda: {"AGENT_MAX_ITERATIONS": "0"}
    )
    assert settings_module.load_settings().agent_max_iterations == 1


def test_settings_clamp_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """신뢰도 기준치는 0~100 범위로 제한되어야 한다."""
    from app.config import settings as settings_module

    monkeypatch.setattr(
        settings_module, "_read_env", lambda: {"AGENT_CONFIDENCE_THRESHOLD": "500"}
    )
    assert settings_module.load_settings().agent_confidence_threshold == 100

    monkeypatch.setattr(
        settings_module, "_read_env", lambda: {"AGENT_CONFIDENCE_THRESHOLD": "-7"}
    )
    assert settings_module.load_settings().agent_confidence_threshold == 0


def test_settings_defaults() -> None:
    """기본값은 '최대 1회 재검색 / 기준 50점' 이어야 한다."""
    from app.config import settings as settings_module

    defaults = settings_module.Settings()
    assert defaults.agent_max_iterations == 2
    assert defaults.agent_confidence_threshold == 50
