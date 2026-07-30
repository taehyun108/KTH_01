"""
OpenAI 호환 LLM 클라이언트 (개발용).

OpenAI 공식 SDK(`openai`)의 AsyncOpenAI 를 사용한다.
`base_url` 만 바꾸면 OpenAI 호환 서버(사내 P-GPT 포함)에 그대로 붙으므로,
이 모듈의 `OpenAICompatibleClient` 를 P-GPT 클라이언트가 상속받아 재사용한다.

⚠️ Provider 별 차이 처리:
  - 도구 스펙: MCP 형태(name/description/inputSchema)
      → OpenAI 형태({"type": "function", "function": {...parameters}}) 로 변환
  - 도구 호출 인자: OpenAI 는 JSON **문자열**로 주므로 dict 로 파싱한다.
"""

from __future__ import annotations

import json
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


class OpenAICompatibleClient(BaseLLMClient):
    """
    OpenAI Chat Completions 규격을 따르는 서버용 클라이언트.

    OpenAI 본사 API 와 사내 P-GPT 가 공통으로 사용한다.
    """

    provider = "openai"

    #: 연결 실패 시 사용자에게 보여줄 서비스 이름 (하위 클래스에서 재정의)
    display_name = "OpenAI"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 16000,
        timeout: float = 120.0,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        """
        Args:
            base_url: API 엔드포인트 (예: https://api.openai.com/v1)
            api_key: 인증 키
            model: 모델 ID
            max_tokens: 응답 최대 토큰 수
            timeout: 요청 타임아웃(초)
            default_headers: 서버가 요구하는 추가 헤더 (사내 게이트웨이 등)
        """
        super().__init__(model=model, max_tokens=max_tokens)
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._default_headers = default_headers or {}
        self._client: Any | None = None

    # ------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------
    def _get_client(self) -> Any:
        """AsyncOpenAI 클라이언트를 지연 생성한다. (import 비용/오프라인 대비)"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover - 설치 누락 시
                raise LLMError(
                    "openai 패키지가 설치되어 있지 않습니다. "
                    "first_time_setup.bat 를 실행해 라이브러리를 설치하세요.",
                    provider=self.provider,
                    cause=exc,
                ) from exc

            if not self._api_key:
                raise LLMError(
                    f"{self.display_name} API 키가 설정되지 않았습니다. "
                    f".env 파일의 키 값을 확인하세요.",
                    provider=self.provider,
                )

            self._client = AsyncOpenAI(
                base_url=self.base_url or None,
                api_key=self._api_key,
                timeout=self._timeout,
                default_headers=self._default_headers or None,
                max_retries=2,
            )
        return self._client

    @staticmethod
    def _convert_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """MCP 형태의 ToolSpec 을 OpenAI function tool 형태로 변환한다."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    # OpenAI 는 JSON Schema 를 `parameters` 로 받는다.
                    "parameters": tool.input_schema
                    or {"type": "object", "properties": {}},
                },
            }
            for tool in tools
        ]

    @staticmethod
    def _parse_tool_calls(message: Any) -> list[ToolCall]:
        """OpenAI 응답에서 도구 호출을 추출한다. (인자는 JSON 문자열 → dict)"""
        raw_calls = getattr(message, "tool_calls", None) or []
        parsed: list[ToolCall] = []
        for call in raw_calls:
            raw_args = getattr(call.function, "arguments", "") or "{}"
            try:
                arguments = json.loads(raw_args)
            except json.JSONDecodeError:
                # 모델이 잘못된 JSON 을 만든 경우: 원문을 보존해 상위에서 판단하게 한다.
                arguments = {"_raw": raw_args}
            parsed.append(
                ToolCall(id=call.id, name=call.function.name, arguments=arguments)
            )
        return parsed

    def _build_payload(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        """공통 요청 페이로드를 만든다."""
        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(message.to_dict() for message in messages)

        return {
            "model": self.model,
            "messages": payload_messages,
            "max_tokens": self._resolve_max_tokens(max_tokens),
        }

    def _wrap_error(self, exc: Exception) -> LLMError:
        """SDK 예외를 사용자용 한글 메시지로 감싼다."""
        name = type(exc).__name__
        if "Authentication" in name or "PermissionDenied" in name:
            message = (
                f"{self.display_name} 인증에 실패했습니다. "
                f".env 파일의 API 키가 올바른지 확인하세요."
            )
        elif "NotFound" in name:
            message = (
                f"{self.display_name} 모델 '{self.model}' 을(를) 찾을 수 없습니다. "
                f".env 파일의 모델 이름을 확인하세요."
            )
        elif "RateLimit" in name:
            message = f"{self.display_name} 요청 한도를 초과했습니다. 잠시 후 다시 시도하세요."
        elif "Connection" in name or "Timeout" in name:
            message = (
                f"{self.display_name} 서버에 연결할 수 없습니다. "
                f"주소({self.base_url})와 네트워크 상태를 확인하세요."
            )
        else:
            message = f"{self.display_name} 호출 중 오류가 발생했습니다: {exc}"
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
            response = await client.chat.completions.create(**payload)
        except Exception as exc:
            raise self._wrap_error(exc) from exc

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=choice.message.content or "",
            model=getattr(response, "model", self.model),
            tool_calls=self._parse_tool_calls(choice.message),
            finish_reason=choice.finish_reason or "",
            usage=TokenUsage(
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
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
        payload["stream"] = True

        try:
            stream = await client.chat.completions.create(**payload)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None)
                if text:
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
        except Exception as exc:  # noqa: BLE001 - 예상 못한 오류도 사용자 메시지로
            return False, f"{self.display_name} 연결 확인 실패: {exc}"
        return True, f"{self.display_name} 연결 정상 (모델: {self.model})"

    async def close(self) -> None:
        """HTTP 연결을 정리한다."""
        if self._client is not None:
            await self._client.close()
            self._client = None


class OpenAIClient(OpenAICompatibleClient):
    """OpenAI 본사 API 클라이언트 (개발용)."""

    provider = "openai"
    display_name = "OpenAI"
