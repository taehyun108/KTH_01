"""
STEP 2 검증: LLM Adapter + 설정 로더 테스트.

네트워크 없이(폐쇄망 가정) 동작해야 하므로 실제 API 는 호출하지 않고,
가짜(Fake) SDK 클라이언트를 주입해 요청 페이로드와 응답 정규화를 검증한다.

검증 항목:
  - 프로젝트 루트/경로가 상대경로로 올바르게 계산되는가 (포터블 원칙)
  - LLM_PROVIDER 값에 따라 구현체가 자동 스위칭되는가
  - MCP 형태의 도구 스펙이 Provider 별 형식으로 정확히 변환되는가
  - Anthropic 호출 시 샘플링 파라미터가 전송되지 않는가 (최신 모델 400 방지)
  - 응답이 LLMResponse 로 정규화되는가 (텍스트 + 도구 호출)
  - 오류가 한글 메시지로 안내되는가
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config.settings import PROJECT_ROOT, Settings, load_settings
from app.llm.anthropic_client import AnthropicClient
from app.llm.base import ChatMessage, LLMError, ToolSpec
from app.llm.factory import LLMClient, create_llm_client
from app.llm.openai_client import OpenAIClient
from app.llm.pgpt_client import PGPTClient

# ============================================================
# 공용 테스트 데이터
# ============================================================

#: MCP 서버가 내보내는 형태의 도구 정의
SAMPLE_MCP_TOOL = {
    "name": "read_file",
    "description": "지정한 파일의 내용을 읽습니다.",
    "inputSchema": {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "읽을 파일 경로"}},
        "required": ["path"],
    },
}


def _settings(**overrides: Any) -> Settings:
    """테스트용 Settings 인스턴스를 만든다."""
    base: dict[str, Any] = {
        "llm_provider": "anthropic",
        "anthropic_api_key": "test-key",
        "anthropic_model": "claude-opus-5",
        "openai_api_key": "test-key",
        "openai_model": "gpt-4o",
        "pgpt_base_url": "https://pgpt.internal/v1",
        "pgpt_api_key": "test-key",
        "pgpt_model": "pgpt-default",
    }
    base.update(overrides)
    return Settings(**base)


# ============================================================
# 1. 설정 로더 (포터블 원칙)
# ============================================================


def test_project_root_is_relative_to_this_file() -> None:
    """프로젝트 루트가 파일 위치 기준으로 계산되어야 한다. (절대경로 하드코딩 금지)"""
    assert PROJECT_ROOT.name == "P-Agent"
    assert (PROJECT_ROOT / "backend" / "app").is_dir()


def test_runtime_paths_are_inside_project_root() -> None:
    """모든 산출물 경로는 프로젝트 폴더 내부여야 한다."""
    settings = load_settings()
    for path in (
        settings.output_dir,
        settings.log_dir,
        settings.data_dir,
        settings.chroma_db_dir,
        settings.action_log_path.parent,
    ):
        assert path.is_relative_to(PROJECT_ROOT), f"{path} 가 프로젝트 폴더 밖에 있습니다"


def test_default_settings_are_safe() -> None:
    """.env 가 없어도 안전한 기본값으로 로드되어야 한다."""
    settings = load_settings()
    assert settings.require_approval is True  # 위험 액션은 기본 승인 필요
    assert settings.kill_switch_key == "esc"
    assert settings.web_search_enabled is False  # 폐쇄망 기본값
    assert isinstance(settings.output_dir, Path)


# ============================================================
# 2. 팩토리 스위칭
# ============================================================


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("anthropic", AnthropicClient),
        ("openai", OpenAIClient),
        ("pgpt", PGPTClient),
        ("PGPT", PGPTClient),  # 대소문자 무시
    ],
)
def test_factory_switches_by_provider(provider: str, expected: type) -> None:
    """LLM_PROVIDER 값에 따라 올바른 구현체가 생성되어야 한다."""
    client = create_llm_client(_settings(llm_provider=provider))
    assert isinstance(client, expected)


def test_factory_from_env_facade() -> None:
    """LLMClient.from_env() 파사드도 동일하게 동작해야 한다."""
    client = LLMClient.from_env(_settings(llm_provider="anthropic"))
    assert isinstance(client, AnthropicClient)
    assert client.model == "claude-opus-5"


def test_factory_rejects_unknown_provider() -> None:
    """알 수 없는 Provider 는 한글 안내와 함께 거부되어야 한다."""
    with pytest.raises(LLMError) as excinfo:
        create_llm_client(_settings(llm_provider="gemini"))
    assert "LLM_PROVIDER" in excinfo.value.message
    assert "pgpt" in excinfo.value.message


def test_pgpt_requires_base_url() -> None:
    """P-GPT 주소가 비어 있으면 친절한 한글 오류가 나야 한다."""
    with pytest.raises(LLMError) as excinfo:
        create_llm_client(_settings(llm_provider="pgpt", pgpt_base_url=""))
    assert "PGPT_BASE_URL" in excinfo.value.message


# ============================================================
# 3. 도구 스펙 변환 (MCP → Provider)
# ============================================================


def test_tool_spec_from_mcp_dict() -> None:
    """MCP dict 형태의 도구를 ToolSpec 으로 변환할 수 있어야 한다."""
    spec = ToolSpec.from_mcp_tool(SAMPLE_MCP_TOOL)
    assert spec.name == "read_file"
    assert spec.input_schema["required"] == ["path"]


def test_tool_spec_from_mcp_object() -> None:
    """MCP SDK 의 Tool 객체(속성 접근)도 변환할 수 있어야 한다."""
    mcp_tool = SimpleNamespace(
        name="capture_screen",
        description="화면을 캡처합니다.",
        inputSchema={"type": "object", "properties": {}},
    )
    spec = ToolSpec.from_mcp_tool(mcp_tool)
    assert spec.name == "capture_screen"
    assert spec.description == "화면을 캡처합니다."


def test_anthropic_tool_conversion() -> None:
    """Anthropic 은 JSON Schema 를 input_schema 키로 받는다."""
    spec = ToolSpec.from_mcp_tool(SAMPLE_MCP_TOOL)
    converted = AnthropicClient._convert_tools([spec])
    assert converted == [
        {
            "name": "read_file",
            "description": "지정한 파일의 내용을 읽습니다.",
            "input_schema": SAMPLE_MCP_TOOL["inputSchema"],
        }
    ]


def test_openai_tool_conversion() -> None:
    """OpenAI 는 function.parameters 형태로 감싸야 한다."""
    spec = ToolSpec.from_mcp_tool(SAMPLE_MCP_TOOL)
    converted = OpenAIClient._convert_tools([spec])
    assert converted[0]["type"] == "function"
    assert converted[0]["function"]["name"] == "read_file"
    assert converted[0]["function"]["parameters"] == SAMPLE_MCP_TOOL["inputSchema"]


# ============================================================
# 4. Anthropic 호출 (가짜 SDK 주입)
# ============================================================


class _FakeAnthropicMessages:
    """anthropic SDK 의 `client.messages` 를 흉내내는 가짜 객체."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.last_payload: dict[str, Any] | None = None

    async def create(self, **payload: Any) -> Any:
        self.last_payload = payload
        return self._response


def _fake_anthropic_response(
    *, stop_reason: str = "end_turn", with_tool: bool = False
) -> Any:
    """Anthropic 응답 객체를 흉내낸다."""
    content: list[Any] = [SimpleNamespace(type="text", text="안녕하세요")]
    if with_tool:
        content.append(
            SimpleNamespace(
                type="tool_use",
                id="toolu_01",
                name="read_file",
                input={"path": "./data/policy.md"},
            )
        )
    return SimpleNamespace(
        content=content,
        model="claude-opus-5",
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=12, output_tokens=5),
    )


async def test_anthropic_chat_normalizes_response() -> None:
    """Anthropic 응답이 LLMResponse 로 정규화되어야 한다."""
    client = AnthropicClient(api_key="k", model="claude-opus-5")
    fake = _FakeAnthropicMessages(_fake_anthropic_response())
    client._client = SimpleNamespace(messages=fake)

    response = await client.chat([ChatMessage(role="user", content="안녕")])

    assert response.content == "안녕하세요"
    assert response.model == "claude-opus-5"
    assert response.finish_reason == "end_turn"
    assert response.usage.input_tokens == 12
    assert response.has_tool_calls is False


async def test_anthropic_chat_extracts_tool_calls() -> None:
    """tool_use 블록이 ToolCall 로 추출되어야 한다."""
    client = AnthropicClient(api_key="k")
    fake = _FakeAnthropicMessages(_fake_anthropic_response(with_tool=True))
    client._client = SimpleNamespace(messages=fake)

    response = await client.chat(
        [ChatMessage(role="user", content="정책 파일 읽어줘")],
        tools=[ToolSpec.from_mcp_tool(SAMPLE_MCP_TOOL)],
    )

    assert response.has_tool_calls is True
    call = response.tool_calls[0]
    assert call.name == "read_file"
    assert call.arguments == {"path": "./data/policy.md"}


async def test_anthropic_payload_omits_sampling_params() -> None:
    """
    최신 Claude 모델은 temperature/top_p/top_k 를 보내면 400 오류가 난다.
    페이로드에 이 값들이 절대 포함되지 않아야 한다.
    """
    client = AnthropicClient(api_key="k")
    fake = _FakeAnthropicMessages(_fake_anthropic_response())
    client._client = SimpleNamespace(messages=fake)

    await client.chat([ChatMessage(role="user", content="안녕")], system="너는 조수야")

    payload = fake.last_payload
    assert payload is not None
    for forbidden in ("temperature", "top_p", "top_k"):
        assert forbidden not in payload, f"{forbidden} 가 전송되면 400 오류가 발생합니다"
    assert payload["system"] == "너는 조수야"
    assert payload["max_tokens"] == 16000


async def test_anthropic_refusal_raises_korean_error() -> None:
    """안전 정책 거절(stop_reason=refusal)은 한글 안내 오류로 변환되어야 한다."""
    client = AnthropicClient(api_key="k")
    fake = _FakeAnthropicMessages(_fake_anthropic_response(stop_reason="refusal"))
    client._client = SimpleNamespace(messages=fake)

    with pytest.raises(LLMError) as excinfo:
        await client.chat([ChatMessage(role="user", content="...")])
    assert "안전 정책" in excinfo.value.message


# ============================================================
# 5. OpenAI 호환 호출 (P-GPT 포함, 가짜 SDK 주입)
# ============================================================


class _FakeCompletions:
    """openai SDK 의 `client.chat.completions` 를 흉내내는 가짜 객체."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.last_payload: dict[str, Any] | None = None

    async def create(self, **payload: Any) -> Any:
        self.last_payload = payload
        return self._response


def _fake_openai_client(response: Any) -> tuple[Any, _FakeCompletions]:
    """가짜 AsyncOpenAI 클라이언트를 만든다."""
    completions = _FakeCompletions(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def _fake_openai_response(*, with_tool: bool = False) -> Any:
    """OpenAI 응답 객체를 흉내낸다."""
    tool_calls = None
    if with_tool:
        tool_calls = [
            SimpleNamespace(
                id="call_01",
                function=SimpleNamespace(
                    name="read_file",
                    # OpenAI 는 인자를 JSON 문자열로 준다.
                    arguments='{"path": "./data/policy.md"}',
                ),
            )
        ]
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="안녕하세요", tool_calls=tool_calls),
                finish_reason="tool_calls" if with_tool else "stop",
            )
        ],
        model="pgpt-default",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4),
    )


async def test_pgpt_chat_normalizes_response() -> None:
    """P-GPT(OpenAI 호환) 응답도 동일한 LLMResponse 로 정규화되어야 한다."""
    client = PGPTClient(
        base_url="https://pgpt.internal/v1", api_key="k", model="pgpt-default"
    )
    fake_client, completions = _fake_openai_client(_fake_openai_response())
    client._client = fake_client

    response = await client.chat([ChatMessage(role="user", content="안녕")])

    assert response.content == "안녕하세요"
    assert response.model == "pgpt-default"
    assert response.usage.input_tokens == 10
    assert completions.last_payload is not None
    assert completions.last_payload["model"] == "pgpt-default"


async def test_pgpt_parses_json_string_tool_arguments() -> None:
    """OpenAI 계열의 JSON 문자열 인자가 dict 로 파싱되어야 한다."""
    client = PGPTClient(base_url="https://pgpt.internal/v1", api_key="k", model="m")
    fake_client, _ = _fake_openai_client(_fake_openai_response(with_tool=True))
    client._client = fake_client

    response = await client.chat(
        [ChatMessage(role="user", content="정책 파일 읽어줘")],
        tools=[ToolSpec.from_mcp_tool(SAMPLE_MCP_TOOL)],
    )

    assert response.has_tool_calls is True
    assert response.tool_calls[0].arguments == {"path": "./data/policy.md"}


async def test_pgpt_system_prompt_goes_first() -> None:
    """시스템 프롬프트는 messages 맨 앞에 system 역할로 들어가야 한다."""
    client = PGPTClient(base_url="https://pgpt.internal/v1", api_key="k", model="m")
    fake_client, completions = _fake_openai_client(_fake_openai_response())
    client._client = fake_client

    await client.chat(
        [ChatMessage(role="user", content="안녕")], system="너는 보고서 작성 도우미야"
    )

    messages = completions.last_payload["messages"]
    assert messages[0] == {"role": "system", "content": "너는 보고서 작성 도우미야"}
    assert messages[1] == {"role": "user", "content": "안녕"}


# ============================================================
# 6. 공통 검증 규칙
# ============================================================


async def test_empty_messages_rejected() -> None:
    """빈 대화는 한글 안내와 함께 거부되어야 한다."""
    client = AnthropicClient(api_key="k")
    with pytest.raises(LLMError) as excinfo:
        await client.chat([])
    assert "비어" in excinfo.value.message


async def test_first_message_must_be_user() -> None:
    """첫 메시지가 assistant 면 거부되어야 한다."""
    client = AnthropicClient(api_key="k")
    with pytest.raises(LLMError) as excinfo:
        await client.chat([ChatMessage(role="assistant", content="안녕")])
    assert "사용자" in excinfo.value.message


async def test_missing_api_key_gives_korean_message() -> None:
    """API 키가 없으면 .env 를 확인하라는 한글 안내가 나와야 한다."""
    client = AnthropicClient(api_key="")
    with pytest.raises(LLMError) as excinfo:
        await client.chat([ChatMessage(role="user", content="안녕")])
    assert "ANTHROPIC_API_KEY" in excinfo.value.message
