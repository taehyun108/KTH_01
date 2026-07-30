"""
Anthropic Claude 클라이언트 (개발용).

Anthropic 공식 SDK(`anthropic`)의 AsyncAnthropic 을 사용한다.

⚠️ 최신 Claude 모델(Opus 5 / Opus 4.7·4.8 계열) 주의사항:
  1. `temperature` / `top_p` / `top_k` 를 보내면 **400 오류**가 발생한다.
     → 이 클라이언트는 샘플링 파라미터를 일절 전송하지 않는다.
        (응답 성향 조절이 필요하면 시스템 프롬프트로 지시한다)
  2. `thinking` 파라미터는 지정하지 않는다.
     → Opus 5 는 기본적으로 adaptive thinking 이 동작하며,
       `max_tokens` 는 thinking + 응답 텍스트를 합산해 제한하므로
       기본값을 넉넉히(16000) 잡는다.
  3. 안전 분류기가 요청을 거절하면 HTTP 200 + `stop_reason="refusal"` 로 온다.
     → 반드시 `stop_reason` 을 먼저 확인한 뒤 content 를 읽는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import (
    BaseLLMClient,
    ChatMessage,
    LLMError,
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolSpec,
)


class AnthropicClient(BaseLLMClient):
    """Anthropic Claude API 클라이언트."""

    provider = "anthropic"
    display_name = "Anthropic Claude"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-opus-5",
        max_tokens: int = 16000,
        timeout: float = 120.0,
    ) -> None:
        """
        Args:
            api_key: Anthropic API 키 (.env 의 ANTHROPIC_API_KEY)
            model: 모델 ID (.env 의 ANTHROPIC_MODEL, 기본 claude-opus-5)
            max_tokens: 응답 최대 토큰 수 (thinking 포함하므로 넉넉히)
            timeout: 요청 타임아웃(초)
        """
        super().__init__(model=model, max_tokens=max_tokens)
        self._api_key = api_key
        self._timeout = timeout
        self._client: Any | None = None

    # ------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------
    def _get_client(self) -> Any:
        """AsyncAnthropic 클라이언트를 지연 생성한다."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:  # pragma: no cover - 설치 누락 시
                raise LLMError(
                    "anthropic 패키지가 설치되어 있지 않습니다. "
                    "first_time_setup.bat 를 실행해 라이브러리를 설치하세요.",
                    provider=self.provider,
                    cause=exc,
                ) from exc

            if not self._api_key:
                raise LLMError(
                    "Anthropic API 키가 설정되지 않았습니다. "
                    ".env 파일의 ANTHROPIC_API_KEY 를 확인하세요.",
                    provider=self.provider,
                )

            self._client = AsyncAnthropic(
                api_key=self._api_key,
                timeout=self._timeout,
                max_retries=2,
            )
        return self._client

    @staticmethod
    def _convert_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """
        MCP 형태의 ToolSpec 을 Anthropic tool 형태로 변환한다.

        Anthropic 은 JSON Schema 를 `input_schema` 로 받으므로
        MCP 의 `inputSchema` 와 사실상 동일하다. (키 이름만 변환)
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema
                or {"type": "object", "properties": {}},
            }
            for tool in tools
        ]

    @staticmethod
    def _extract(response: Any) -> tuple[str, list[ToolCall]]:
        """응답의 content 블록에서 텍스트와 도구 호출을 분리한다."""
        texts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                texts.append(block.text)
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        # Anthropic 은 이미 파싱된 dict 로 준다.
                        arguments=dict(block.input or {}),
                    )
                )
        return "".join(texts), tool_calls

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """
        공통 요청 페이로드를 만든다.

        샘플링 파라미터(temperature/top_p/top_k)는 최신 모델에서 400 오류를
        유발하므로 **의도적으로 포함하지 않는다.**
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self._resolve_max_tokens(max_tokens),
            "messages": [message.to_dict() for message in messages],
        }
        if system:
            payload["system"] = system
        return payload

    def _wrap_error(self, exc: Exception) -> LLMError:
        """SDK 예외를 사용자용 한글 메시지로 감싼다."""
        name = type(exc).__name__
        if "Authentication" in name or "PermissionDenied" in name:
            message = (
                "Anthropic 인증에 실패했습니다. "
                ".env 파일의 ANTHROPIC_API_KEY 가 올바른지 확인하세요."
            )
        elif "NotFound" in name:
            message = (
                f"Claude 모델 '{self.model}' 을(를) 찾을 수 없습니다. "
                ".env 파일의 ANTHROPIC_MODEL 값을 확인하세요."
            )
        elif "RateLimit" in name:
            message = "Anthropic 요청 한도를 초과했습니다. 잠시 후 다시 시도하세요."
        elif "Connection" in name or "Timeout" in name:
            message = (
                "Anthropic 서버에 연결할 수 없습니다. 인터넷 연결을 확인하세요. "
                "(사내 폐쇄망에서는 LLM_PROVIDER=pgpt 로 설정해야 합니다)"
            )
        else:
            message = f"Claude 호출 중 오류가 발생했습니다: {exc}"
        return LLMError(message, provider=self.provider, cause=exc)

    # ------------------------------------------------------------
    # BaseLLMClient 구현
    # ------------------------------------------------------------
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """대화를 한 턴 진행한다."""
        self._validate_messages(messages)
        client = self._get_client()
        payload = self._build_payload(messages, system=system, max_tokens=max_tokens)
        if tools:
            payload["tools"] = self._convert_tools(tools)

        try:
            response = await client.messages.create(**payload)
        except Exception as exc:
            raise self._wrap_error(exc) from exc

        stop_reason = getattr(response, "stop_reason", "") or ""

        # 안전 분류기가 거절한 경우 content 가 비어 있을 수 있으므로 먼저 처리한다.
        if stop_reason == "refusal":
            raise LLMError(
                "요청하신 내용은 모델의 안전 정책에 따라 처리할 수 없습니다. "
                "질문을 다르게 표현해 다시 시도해 주세요.",
                provider=self.provider,
            )

        content, tool_calls = self._extract(response)
        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=content,
            model=getattr(response, "model", self.model),
            tool_calls=tool_calls,
            finish_reason=stop_reason,
            usage=TokenUsage(
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
            ),
            raw=response,
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """응답을 텍스트 조각 단위로 스트리밍한다."""
        self._validate_messages(messages)
        client = self._get_client()
        payload = self._build_payload(messages, system=system, max_tokens=max_tokens)

        try:
            async with client.messages.stream(**payload) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    async def health_check(self) -> tuple[bool, str]:
        """짧은 요청을 보내 연결 상태를 확인한다."""
        try:
            await self.chat(
                [ChatMessage(role="user", content="ping")],
                max_tokens=16,
            )
        except LLMError as exc:
            return False, exc.message
        except Exception as exc:  # noqa: BLE001
            return False, f"Anthropic 연결 확인 실패: {exc}"
        return True, f"Anthropic Claude 연결 정상 (모델: {self.model})"

    async def close(self) -> None:
        """HTTP 연결을 정리한다."""
        if self._client is not None:
            await self._client.close()
            self._client = None
