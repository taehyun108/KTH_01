"""
GUI 자동 조작 루프 검증 (OpenClaw 형 컴퓨터 조작 방식).

이 컨테이너에는 실제 화면이 없으므로, **화면 인식과 조작 도구를 가짜로 대체**해
루프의 판단·정지·안전 동작을 검증한다. (실제 클릭은 회사 PC 에서만 가능)

검증 항목
---------
1. 조작 결정 파싱 (JSON / 코드블록 / 잡텍스트 섞임)
2. 조작 전 검증 — 화면에 없는 것을 누르지 않는가
3. 제자리 감지 — 같은 조작 반복 시 멈추는가
4. **루프가 목표 달성 시 멈추는가 / 상한에서 멈추는가** (폭주 방지)
5. 화면을 볼 수 없으면 조작하지 않는가 (안전)
6. Kill Switch 가 루프 중간에 듣는가
7. LLM 을 쓸 수 없으면 계획 대본으로 대체되는가 (폐쇄망)
8. 설정으로 루프를 끌 수 있는가
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.agents import executor, gui_loop
from app.agents.gui_loop import ActionDecision, build_prompt, format_elements, is_stuck
from app.agents.runtime import AgentRuntime, EventBus, KilledError
from app.agents.state import initial_state
from app.config.settings import MAX_GUI_STEPS, load_settings
from app.llm.base import BaseLLMClient, ChatMessage, LLMError, LLMResponse, ToolSpec
from app.mcp_client.client import MCPClient

CONNECT_TIMEOUT = 60.0

#: 조작이 필요하다고 판단되는 요청 (perception.needs_screen 이 True 가 되도록)
GUI_REQUEST = "브라우저를 열고 화면에서 검색 버튼을 클릭해줘"

#: 가짜 화면 요소
FAKE_ELEMENTS: list[dict[str, Any]] = [
    {"text": "검색", "x": 100, "y": 50, "confidence": 0.99},
    {"text": "주소 입력창", "x": 300, "y": 20, "confidence": 0.95},
    {"text": "확인", "x": 200, "y": 400, "confidence": 0.90},
]


# ============================================================
# 가짜 LLM / 가짜 도구
# ============================================================


class ScriptedGuiLLM(BaseLLMClient):
    """정해진 조작 순서를 차례로 돌려주는 LLM."""

    provider = "gui-scripted"

    def __init__(self, actions: list[str]) -> None:
        super().__init__(model="gui-model")
        self.actions = actions
        self.calls = 0

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

        # GUI 조작 판단 요청인지 확인한다.
        if "PC 화면을 조작하는 담당자" in system:
            index = min(self.calls, len(self.actions) - 1)
            self.calls += 1
            return LLMResponse(
                content=self.actions[index], model=self.model, finish_reason="end_turn"
            )

        # 그 밖의 Agent(계획/검증/보고서)는 파이프라인이 끝까지 가도록 최소 응답.
        if "계획 수립" in system:
            content = '["브라우저를 연다", "검색 버튼을 클릭한다"]'
        elif "검증 담당자" in system:
            content = "점수: 90\n사유: 충분합니다."
        elif "보고서를 작성하는 담당자" in system:
            content = "## 개요\n\n본문."
        else:
            content = ""
        return LLMResponse(content=content, model=self.model, finish_reason="end_turn")

    async def stream_chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[str]:
        yield ""

    async def health_check(self) -> tuple[bool, str]:
        return True, "정상"


class DeadGuiLLM(BaseLLMClient):
    """GUI 판단만 실패하는 LLM. (폐쇄망 재현)"""

    provider = "gui-dead"

    def __init__(self) -> None:
        super().__init__(model="dead")

    async def chat(
        self, messages: list[ChatMessage], *, system: str | None = None, **kwargs: Any
    ) -> LLMResponse:
        self._validate_messages(messages)
        raise LLMError("LLM 서버에 연결할 수 없습니다.", provider=self.provider)

    async def stream_chat(
        self, messages: list[ChatMessage], **kwargs: Any
    ) -> AsyncIterator[str]:
        raise LLMError("연결 불가", provider=self.provider)
        yield ""  # pragma: no cover

    async def health_check(self) -> tuple[bool, str]:
        return False, "연결 불가"


class FakeToolRuntime:
    """
    `runtime.call_tool` 만 가짜로 바꿔 화면/조작 도구를 흉내내는 래퍼.

    실제 화면이 없는 환경에서 루프 동작을 검증하기 위한 것이다.
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        elements: list[dict[str, Any]] | None = None,
        screen_ok: bool = True,
        action_ok: bool = True,
    ) -> None:
        self._runtime = runtime
        self._elements = elements if elements is not None else FAKE_ELEMENTS
        self._screen_ok = screen_ok
        self._action_ok = action_ok
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        """가짜로 만들지 않은 속성은 실제 런타임으로 넘긴다."""
        return getattr(self._runtime, name)

    async def call_tool(
        self,
        step: str,
        qualified_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        run_id: str = "",
    ) -> dict[str, Any]:
        """화면/조작 도구 호출을 가로채 가짜 결과를 돌려준다."""
        args = arguments or {}
        self.calls.append((qualified_name, args))

        def log(ok: bool, summary: str) -> dict[str, Any]:
            return {
                "step": step,
                "tool": qualified_name.replace("__", "."),
                "arguments": args,
                "ok": ok,
                "summary": summary,
            }

        if qualified_name == "screen__list_ui_elements":
            if not self._screen_ok:
                return {
                    "ok": False,
                    "text": "화면을 캡처할 수 없습니다.",
                    "structured": None,
                    "log": log(False, "화면 인식 실패"),
                }
            return {
                "ok": True,
                "text": f"요소 {len(self._elements)}개",
                "structured": {"elements": self._elements, "count": len(self._elements)},
                "log": log(True, "화면 인식 성공"),
            }

        if qualified_name.startswith("automation__"):
            return {
                "ok": self._action_ok,
                "text": "" if self._action_ok else "승인이 거절되었습니다.",
                "structured": None,
                "log": log(self._action_ok, "조작"),
            }

        if qualified_name == "screen__find_ui_element":
            return {
                "ok": False,
                "text": "요소를 찾지 못했습니다.",
                "structured": None,
                "log": log(False, "탐지 실패"),
            }

        # 그 밖의 도구는 실제 MCP 서버로 넘긴다.
        return await self._runtime.call_tool(
            step, qualified_name, args, run_id=run_id
        )


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
    gui_max_steps: int = 5,
    gui_loop_enabled: bool = True,
) -> AgentRuntime:
    """GUI 루프 설정을 지정한 런타임을 만든다."""
    settings = dataclasses.replace(
        load_settings(),
        gui_max_steps=gui_max_steps,
        gui_loop_enabled=gui_loop_enabled,
    )
    return AgentRuntime.create(
        mcp_client, settings=settings, llm=llm, event_bus=EventBus()
    )


async def _run_executor(
    runtime: Any,
    *,
    request: str = GUI_REQUEST,
    run_id: str = "t-gui",
    plan: list[str] | None = None,
) -> dict[str, Any]:
    """Executor 노드만 단독 실행한다."""
    state = initial_state(run_id, request)
    state["plan"] = (
        plan if plan is not None else ["브라우저를 연다", "검색 버튼을 클릭한다"]
    )
    state["observations"] = ["화면 캡처 완료"]
    runtime.register_run(run_id)
    return await executor.run(state, runtime)


# ============================================================
# 1. 조작 결정 파싱
# ============================================================


def test_parse_action_plain_json() -> None:
    """평범한 JSON 을 파싱해야 한다."""
    decision = gui_loop.parse_action('{"action": "click", "target": "검색", "reason": "r"}')
    assert decision is not None
    assert decision.action == "click"
    assert decision.target == "검색"
    assert decision.is_acting is True
    assert decision.is_terminal is False


def test_parse_action_code_fence() -> None:
    """코드블록으로 감싸 와도 파싱해야 한다."""
    decision = gui_loop.parse_action('```json\n{"action": "done", "reason": "끝"}\n```')
    assert decision is not None
    assert decision.action == "done"
    assert decision.is_terminal is True


def test_parse_action_with_surrounding_text() -> None:
    """앞뒤에 설명이 붙어 와도 JSON 객체를 찾아내야 한다."""
    raw = '다음 조작입니다:\n{"action": "key", "key": "enter"}\n이유는 위와 같습니다.'
    decision = gui_loop.parse_action(raw)
    assert decision is not None
    assert decision.action == "key"
    assert decision.key == "enter"


def test_parse_action_rejects_unknown_action() -> None:
    """모르는 조작은 거부해야 한다. (엉뚱한 동작 방지)"""
    assert gui_loop.parse_action('{"action": "format_disk"}') is None
    assert gui_loop.parse_action('{"action": "shutdown", "reason": "x"}') is None


def test_parse_action_rejects_garbage() -> None:
    """JSON 이 아니면 None 을 반환해 루프가 안전하게 멈추게 해야 한다."""
    assert gui_loop.parse_action("") is None
    assert gui_loop.parse_action("잘 모르겠습니다") is None
    assert gui_loop.parse_action("{망가진 json") is None


def test_decision_signature_ignores_reason() -> None:
    """이유가 달라도 같은 조작이면 같은 지문이어야 한다. (제자리 감지용)"""
    a = ActionDecision(action="click", target="검색", reason="첫 시도")
    b = ActionDecision(action="click", target="검색", reason="다시 시도")
    assert a.signature() == b.signature()


def test_decision_describe_is_korean() -> None:
    """사용자에게 보여줄 설명이 한글이어야 한다."""
    assert "클릭" in ActionDecision(action="click", target="검색").describe()
    assert "입력" in ActionDecision(action="type", text="가").describe()
    assert "키" in ActionDecision(action="key", key="enter").describe()


# ============================================================
# 2. 조작 전 검증
# ============================================================


def test_validate_rejects_target_not_on_screen() -> None:
    """화면에 없는 것을 누르려 하면 막아야 한다. (오클릭 방지)"""
    decision = ActionDecision(action="click", target="없는버튼")
    problem = gui_loop.validate_decision(decision, FAKE_ELEMENTS)
    assert problem is not None
    assert "없어" in problem


def test_validate_allows_target_on_screen() -> None:
    """화면에 있는 요소는 통과해야 한다."""
    decision = ActionDecision(action="click", target="검색")
    assert gui_loop.validate_decision(decision, FAKE_ELEMENTS) is None


def test_validate_allows_partial_match() -> None:
    """부분 일치도 허용해야 한다. (OCR 결과가 조금 다를 수 있음)"""
    decision = ActionDecision(action="click", target="주소")
    assert gui_loop.validate_decision(decision, FAKE_ELEMENTS) is None


def test_validate_rejects_empty_fields() -> None:
    """필수 값이 비어 있으면 조작하지 않아야 한다."""
    assert gui_loop.validate_decision(ActionDecision(action="click"), []) is not None
    assert gui_loop.validate_decision(ActionDecision(action="type"), []) is not None
    assert gui_loop.validate_decision(ActionDecision(action="key"), []) is not None
    assert (
        gui_loop.validate_decision(ActionDecision(action="open_browser"), []) is not None
    )


# ============================================================
# 3. 제자리 감지 / 프롬프트
# ============================================================


def test_is_stuck_detects_repetition() -> None:
    """같은 조작이 연속되면 제자리로 판단해야 한다."""
    assert is_stuck(["click|검색", "click|검색", "click|검색"]) is True


def test_is_stuck_allows_progress() -> None:
    """조작이 달라지면 제자리가 아니다."""
    assert is_stuck(["click|검색", "type|가", "click|검색"]) is False
    assert is_stuck(["click|검색", "click|검색"]) is False


def test_format_elements_includes_coordinates() -> None:
    """프롬프트에 요소 글자와 좌표가 들어가야 한다."""
    text = format_elements(FAKE_ELEMENTS)
    assert "검색" in text
    assert "100" in text


def test_format_elements_handles_empty() -> None:
    """요소가 없어도 프롬프트를 만들 수 있어야 한다."""
    assert "없습니다" in format_elements([])


def test_build_prompt_contains_goal_and_progress() -> None:
    """판단 요청문에 목표·화면·이력·진행 상황이 모두 들어가야 한다."""
    prompt = build_prompt(
        "검색 버튼을 눌러줘", FAKE_ELEMENTS, ["'검색' 클릭 → 성공"], step=2, max_steps=5
    )
    assert "검색 버튼을 눌러줘" in prompt
    assert "검색" in prompt
    assert "2/5" in prompt


# ============================================================
# 4. ★ 루프 종료 (폭주 방지)
# ============================================================


async def test_loop_stops_on_done(mcp_client: MCPClient) -> None:
    """LLM 이 done 을 내면 즉시 멈춰야 한다."""
    llm = ScriptedGuiLLM(
        [
            '{"action": "click", "target": "검색", "reason": "검색 시작"}',
            '{"action": "done", "reason": "목표 달성"}',
        ]
    )
    runtime = FakeToolRuntime(_make_runtime(mcp_client, llm, gui_max_steps=10))

    result = await _run_executor(runtime)

    assert result["gui_steps"] == 1, "조작 1회 후 done 이어야 한다"
    assert any("목표를 달성" in item for item in result["executions"])
    # 클릭이 실제로 요청됐는지 확인
    assert any(name == "automation__click" for name, _ in runtime.calls)


async def test_loop_stops_at_step_limit(mcp_client: MCPClient) -> None:
    """
    LLM 이 **끝없이 조작을 요구해도** 상한에서 멈춰야 한다.

    GUI 를 실제로 조작하는 기능이므로 폭주는 가장 위험한 실패 모드다.
    (매번 다른 조작을 내도록 해서 제자리 감지가 아니라 상한으로 멈추게 한다)
    """
    llm = ScriptedGuiLLM(
        [
            '{"action": "click", "target": "검색", "reason": "1"}',
            '{"action": "click", "target": "확인", "reason": "2"}',
            '{"action": "type", "text": "가", "reason": "3"}',
            '{"action": "key", "key": "enter", "reason": "4"}',
            '{"action": "click", "target": "주소 입력창", "reason": "5"}',
            '{"action": "click", "target": "검색", "reason": "6"}',
            '{"action": "click", "target": "확인", "reason": "7"}',
        ]
    )
    limit = 3
    runtime = FakeToolRuntime(_make_runtime(mcp_client, llm, gui_max_steps=limit))

    result = await _run_executor(runtime)

    assert result["gui_steps"] == limit, "조작 수 상한이 지켜지지 않았다"
    assert any("상한" in note for note in result["notes"])
    # 상한을 넘는 조작이 실행되지 않았어야 한다.
    action_calls = [n for n, _ in runtime.calls if n.startswith("automation__")]
    assert len(action_calls) <= limit


async def test_loop_stops_when_stuck(mcp_client: MCPClient) -> None:
    """같은 조작만 반복하면 제자리로 판단해 멈춰야 한다."""
    same = '{"action": "click", "target": "검색", "reason": "계속 시도"}'
    llm = ScriptedGuiLLM([same])
    runtime = FakeToolRuntime(_make_runtime(mcp_client, llm, gui_max_steps=20))

    result = await _run_executor(runtime)

    assert any("반복" in note for note in result["notes"]), "제자리 감지가 동작하지 않았다"
    # 상한(20)까지 가지 않고 훨씬 일찍 멈춰야 한다.
    assert result["gui_steps"] < 20


async def test_loop_stops_on_give_up(mcp_client: MCPClient) -> None:
    """LLM 이 give_up 하면 멈추고 사유를 남겨야 한다."""
    llm = ScriptedGuiLLM(['{"action": "give_up", "reason": "대상을 찾을 수 없음"}'])
    runtime = FakeToolRuntime(_make_runtime(mcp_client, llm))

    result = await _run_executor(runtime)

    assert result["gui_steps"] == 0
    assert any("중단" in item for item in result["executions"])
    # 조작은 하나도 하지 않았어야 한다.
    assert not any(n.startswith("automation__") for n, _ in runtime.calls)


async def test_loop_stops_on_unparsable_decision(mcp_client: MCPClient) -> None:
    """판단 결과를 이해할 수 없으면 조작하지 않고 멈춰야 한다."""
    llm = ScriptedGuiLLM(["무슨 말인지 모르겠습니다"])
    runtime = FakeToolRuntime(_make_runtime(mcp_client, llm))

    await _run_executor(runtime, plan=["검색 버튼을 클릭한다"])

    assert not any(n.startswith("automation__") for n, _ in runtime.calls)


# ============================================================
# 5. 화면을 볼 수 없을 때 (안전)
# ============================================================


async def test_no_action_without_screen(mcp_client: MCPClient) -> None:
    """화면 인식이 실패하면 조작을 시도해서는 안 된다."""
    llm = ScriptedGuiLLM(['{"action": "click", "target": "검색", "reason": "x"}'])
    runtime = FakeToolRuntime(
        _make_runtime(mcp_client, llm), screen_ok=False
    )

    result = await _run_executor(runtime)

    assert not any(
        n.startswith("automation__") for n, _ in runtime.calls
    ), "화면을 못 봤는데 조작을 시도했다 (위험)"
    assert any("화면" in note for note in result["notes"])


async def test_perception_marker_blocks_actions(mcp_client: MCPClient) -> None:
    """Perception 이 화면 인식 불가를 알리면 루프 자체를 시작하지 않아야 한다."""
    llm = ScriptedGuiLLM(['{"action": "click", "target": "검색", "reason": "x"}'])
    runtime = FakeToolRuntime(_make_runtime(mcp_client, llm))

    state = initial_state("t-noscreen", GUI_REQUEST)
    state["plan"] = ["검색 버튼을 클릭한다"]
    state["observations"] = ["화면 인식을 사용할 수 없어 화면 정보 없이 진행합니다."]
    runtime.register_run("t-noscreen")

    result = await executor.run(state, runtime)

    assert result["gui_steps"] == 0
    assert runtime.calls == [], "화면 인식 불가 상태에서 도구를 호출했다"


async def test_skips_when_no_gui_needed(mcp_client: MCPClient) -> None:
    """
    조작이 필요 없는 요청이면 아무것도 하지 않아야 한다.

    요청문과 계획 **양쪽 모두** 화면 조작 키워드가 없어야 건너뛴다.
    (계획에 '클릭' 이 있으면 조작이 필요한 것으로 본다)
    """
    llm = ScriptedGuiLLM(['{"action": "done", "reason": "x"}'])
    runtime = FakeToolRuntime(_make_runtime(mcp_client, llm))

    result = await _run_executor(
        runtime,
        request="사내 자료를 정리해줘",
        plan=["사내 문서를 찾는다", "보고서를 작성한다"],
    )

    assert result["gui_steps"] == 0
    assert runtime.calls == []
    assert llm.calls == 0, "조작이 필요 없는데 판단 LLM 을 호출했다"


# ============================================================
# 6. Kill Switch
# ============================================================


async def test_kill_switch_stops_loop(mcp_client: MCPClient) -> None:
    """루프 도중 중단하면 즉시 멈춰야 한다."""
    llm = ScriptedGuiLLM(['{"action": "click", "target": "검색", "reason": "x"}'])
    base = _make_runtime(mcp_client, llm, gui_max_steps=20)
    runtime = FakeToolRuntime(base)

    run_id = "t-kill-gui"
    state = initial_state(run_id, GUI_REQUEST)
    state["plan"] = ["검색 버튼을 클릭한다"]
    state["observations"] = ["화면 캡처 완료"]
    base.register_run(run_id)
    base.kill(run_id)  # 시작 전에 중단 신호

    with pytest.raises(KilledError):
        await executor.run(state, runtime)


# ============================================================
# 7. LLM 장애 / 설정으로 끄기
# ============================================================


async def test_falls_back_to_plan_script_without_llm(mcp_client: MCPClient) -> None:
    """
    LLM 을 쓸 수 없으면 계획 대본 실행으로 대체되어야 한다.

    폐쇄망에서 P-GPT 가 응답하지 않아도 아무것도 못 하는 상태가 되면 안 된다.
    """
    runtime = FakeToolRuntime(_make_runtime(mcp_client, DeadGuiLLM()))

    # 계획 대본 방식은 문장에서 URL 을 직접 뽑아 쓴다.
    result = await _run_executor(
        runtime, plan=["브라우저로 https://www.korea.kr 에 접속한다"]
    )

    assert any("계획 순서대로" in note for note in result["notes"])
    # 대체 경로가 실제로 조작을 수행했는지 확인한다.
    assert any(n == "automation__open_browser" for n, _ in runtime.calls)


async def test_loop_can_be_disabled_by_setting(mcp_client: MCPClient) -> None:
    """GUI_LOOP_ENABLED=false 면 루프를 쓰지 않아야 한다."""
    llm = ScriptedGuiLLM(['{"action": "click", "target": "검색", "reason": "x"}'])
    runtime = FakeToolRuntime(
        _make_runtime(mcp_client, llm, gui_loop_enabled=False)
    )

    result = await _run_executor(runtime)

    assert any("꺼져 있어" in note for note in result["notes"])
    assert llm.calls == 0, "루프를 껐는데 판단 LLM 을 호출했다"
    # 화면 인식도 하지 않아야 한다.
    assert not any(n == "screen__list_ui_elements" for n, _ in runtime.calls)


# ============================================================
# 8. 설정 상한
# ============================================================


def test_gui_max_steps_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` 에 과한 값을 넣어도 하드 상한으로 잘려야 한다."""
    from app.config import settings as settings_module

    monkeypatch.setattr(
        settings_module, "_read_env", lambda: {"GUI_MAX_STEPS": "9999"}
    )
    assert settings_module.load_settings().gui_max_steps == MAX_GUI_STEPS

    monkeypatch.setattr(settings_module, "_read_env", lambda: {"GUI_MAX_STEPS": "0"})
    assert settings_module.load_settings().gui_max_steps == 1


def test_gui_loop_enabled_by_default() -> None:
    """기본값은 '루프 사용' 이어야 한다."""
    from app.config import settings as settings_module

    defaults = settings_module.Settings()
    assert defaults.gui_loop_enabled is True
    assert defaults.gui_max_steps == 15


async def test_gui_action_event_is_emitted(mcp_client: MCPClient) -> None:
    """조작마다 이벤트를 보내 화면에서 진행 상황을 볼 수 있어야 한다."""
    llm = ScriptedGuiLLM(
        [
            '{"action": "click", "target": "검색", "reason": "검색 시작"}',
            '{"action": "done", "reason": "완료"}',
        ]
    )
    base = _make_runtime(mcp_client, llm, gui_max_steps=10)
    runtime = FakeToolRuntime(base)

    run_id = "t-gui-event"
    await _run_executor(runtime, run_id=run_id)

    events = base.event_bus.history(run_id)
    actions = [e for e in events if e.type == "gui_action"]
    assert actions, "gui_action 이벤트가 발생하지 않았다"
    assert actions[0].payload["action"] == "click"
    assert "검색" in actions[0].payload["summary"]
    assert actions[0].payload["reason"] == "검색 시작"
