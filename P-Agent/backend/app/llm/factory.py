"""
LLM Provider 팩토리.

⚠️ 개발 규칙: P-Agent 의 **모든 LLM 호출은 반드시 이 팩토리를 통해서만** 생성한다.
   Agent 코드에서 AnthropicClient / OpenAIClient 를 직접 import 하지 말 것.

`.env` 의 LLM_PROVIDER 값에 따라 구현체가 자동으로 결정된다.

    LLM_PROVIDER=anthropic  → AnthropicClient (개발용)
    LLM_PROVIDER=openai     → OpenAIClient    (개발용)
    LLM_PROVIDER=pgpt       → PGPTClient      (배포용, 기본값)

사용 예:
    from app.llm.factory import LLMClient

    client = LLMClient.from_env()
    response = await client.chat([ChatMessage(role="user", content="안녕")])
"""

from __future__ import annotations

from typing import Final

from app.config.settings import Settings, get_settings
from app.llm.anthropic_client import AnthropicClient
from app.llm.base import BaseLLMClient, LLMError
from app.llm.openai_client import OpenAIClient
from app.llm.pgpt_client import PGPTClient

#: 지원하는 Provider 목록 (오류 메시지 안내용)
SUPPORTED_PROVIDERS: Final[tuple[str, ...]] = ("pgpt", "anthropic", "openai")


def create_llm_client(settings: Settings | None = None) -> BaseLLMClient:
    """
    설정에 맞는 LLM 클라이언트를 생성한다.

    Args:
        settings: 사용할 설정. 생략하면 `.env` 에서 로드한 전역 설정을 사용한다.

    Returns:
        BaseLLMClient 구현체.

    Raises:
        LLMError: 지원하지 않는 Provider 이거나 필수 설정이 누락된 경우.
    """
    settings = settings or get_settings()
    provider = (settings.llm_provider or "pgpt").strip().lower()

    if provider == "pgpt":
        return PGPTClient(
            base_url=settings.pgpt_base_url,
            api_key=settings.pgpt_api_key,
            model=settings.pgpt_model,
        )

    if provider == "anthropic":
        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )

    if provider == "openai":
        return OpenAIClient(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )

    raise LLMError(
        f"알 수 없는 LLM Provider 입니다: '{provider}'. "
        f".env 파일의 LLM_PROVIDER 를 다음 중 하나로 설정하세요: "
        f"{', '.join(SUPPORTED_PROVIDERS)}",
        provider=provider,
    )


class LLMClient:
    """
    LLM 클라이언트 생성용 파사드(facade).

    인스턴스를 만들지 않고 `LLMClient.from_env()` 만 호출해 사용한다.
    """

    @classmethod
    def from_env(cls, settings: Settings | None = None) -> BaseLLMClient:
        """
        `.env` 설정을 읽어 알맞은 LLM 클라이언트를 반환한다.

        Example:
            client = LLMClient.from_env()
        """
        return create_llm_client(settings)

    @staticmethod
    def supported_providers() -> tuple[str, ...]:
        """지원하는 Provider 목록을 반환한다."""
        return SUPPORTED_PROVIDERS
