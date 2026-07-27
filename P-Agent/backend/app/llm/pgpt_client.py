"""
사내 P-GPT 클라이언트 (배포용).

P-GPT 는 OpenAI 호환 형식(Chat Completions)을 제공한다고 가정한다.
따라서 OpenAICompatibleClient 를 그대로 상속받고,
**엔드포인트 / 인증 헤더 / 모델 이름만 .env 로 교체**한다.

향후 P-GPT 규격이 OpenAI 와 달라지면 이 파일만 수정하면 되며,
Agent 코드는 전혀 건드리지 않는다.
"""

from __future__ import annotations

from app.llm.base import LLMError
from app.llm.openai_client import OpenAICompatibleClient


class PGPTClient(OpenAICompatibleClient):
    """
    사내 P-GPT LLM 클라이언트.

    Example:
        client = PGPTClient(
            base_url="https://내부-pgpt/v1",
            api_key="...",
            model="pgpt-default",
        )
    """

    provider = "pgpt"
    display_name = "사내 P-GPT"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 16000,
        timeout: float = 180.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """
        Args:
            base_url: 사내 P-GPT 엔드포인트 (.env 의 PGPT_BASE_URL)
            api_key: 사내 발급 키 (.env 의 PGPT_API_KEY)
            model: 사내 모델 이름 (.env 의 PGPT_MODEL)
            max_tokens: 응답 최대 토큰 수
            timeout: 요청 타임아웃(초). 사내망은 느릴 수 있어 기본값을 넉넉히 잡는다.
            extra_headers: 사내 게이트웨이가 요구하는 추가 헤더가 있으면 전달
        """
        if not base_url:
            raise LLMError(
                "사내 P-GPT 주소(PGPT_BASE_URL)가 설정되지 않았습니다. "
                ".env 파일을 열어 회사에서 받은 주소를 입력하세요.",
                provider=self.provider,
            )

        super().__init__(
            base_url=base_url,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            timeout=timeout,
            default_headers=extra_headers,
        )
