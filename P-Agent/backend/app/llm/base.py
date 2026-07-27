"""
LLM Adapter 베이스 정의.

P-Agent 의 모든 LLM 호출은 이 인터페이스를 통해서만 이루어진다.
Provider(P-GPT / Claude / GPT)가 바뀌어도 Agent 코드는 수정하지 않는다.

핵심 설계:
  - 도구(tool) 스펙은 **MCP 표준 형태**(name / description / inputSchema)로 통일한다.
    → STEP 3 의 자체 MCP 서버가 내보내는 Tool 을 그대로 LLM 에 전달 가능.
    → Provider 별 변환(Anthropic `input_schema` / OpenAI `function.parameters`)은
      각 클라이언트 내부에서 처리한다.
  - 응답은 LLMResponse 로 정규화한다. (텍스트 + 도구 호출 + 사용량)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

#: 대화 역할
Role = Literal["user", "assistant"]


class LLMError(RuntimeError):
    """
    LLM 호출 관련 오류.

    사용자(비개발자)에게 그대로 보여줄 수 있도록 한글 메시지를 담는다.
    """

    def __init__(self, message: str, *, provider: str = "", cause: Exception | None = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.cause = cause

    def __str__(self) -> str:  # pragma: no cover - 단순 포맷
        prefix = f"[{self.provider}] " if self.provider else ""
        return f"{prefix}{self.message}"


@dataclass(frozen=True)
class ChatMessage:
    """대화 메시지 한 건."""

    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        """Provider 공통 dict 형태로 변환."""
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ToolSpec:
    """
    LLM 에 전달할 도구 정의 (MCP Tool 과 1:1 대응).

    Attributes:
        name: 도구 이름 (예: "read_file")
        description: 언제 이 도구를 쓰는지 설명. LLM 의 판단 근거가 되므로 구체적으로 작성.
        input_schema: JSON Schema 형태의 입력 스키마 (MCP 의 `inputSchema`).
    """

    name: str
    description: str
    input_schema: dict[str, Any]

    @classmethod
    def from_mcp_tool(cls, tool: Any) -> ToolSpec:
        """
        MCP `Tool` 객체(또는 dict)를 ToolSpec 으로 변환한다.

        MCP SDK 의 Tool 은 `name` / `description` / `inputSchema` 속성을 가진다.
        """
        if isinstance(tool, dict):
            return cls(
                name=tool["name"],
                description=tool.get("description") or "",
                input_schema=tool.get("inputSchema") or tool.get("input_schema") or {},
            )
        return cls(
            name=tool.name,
            description=getattr(tool, "description", "") or "",
            input_schema=getattr(tool, "inputSchema", None) or {},
        )


@dataclass(frozen=True)
class ToolCall:
    """LLM 이 요청한 도구 호출 한 건."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class TokenUsage:
    """토큰 사용량 (비용 추적용)."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    """정규화된 LLM 응답."""

    content: str
    """모델이 생성한 텍스트."""

    model: str
    """실제 응답을 생성한 모델 ID."""

    tool_calls: list[ToolCall] = field(default_factory=list)
    """모델이 호출을 요청한 도구 목록. 비어 있으면 도구 호출 없음."""

    finish_reason: str = ""
    """종료 사유 (end_turn / tool_use / max_tokens / refusal 등)."""

    usage: TokenUsage = field(default_factory=TokenUsage)
    """토큰 사용량."""

    raw: Any = None
    """Provider 원본 응답 객체 (디버깅용)."""

    @property
    def has_tool_calls(self) -> bool:
        """도구 호출 요청이 있는지 여부."""
        return bool(self.tool_calls)


class BaseLLMClient(ABC):
    """
    LLM 클라이언트 공통 인터페이스.

    모든 Provider 구현체(PGPTClient / AnthropicClient / OpenAIClient)는
    이 클래스를 상속받아 구현한다.
    """

    #: Provider 식별자 ("pgpt" / "anthropic" / "openai")
    provider: str = "base"

    def __init__(self, *, model: str, max_tokens: int = 16000) -> None:
        """
        Args:
            model: 사용할 모델 ID.
            max_tokens: 응답 최대 토큰 수. 스트리밍이 아닌 호출의 기본값은 16000.
                        (너무 작으면 답변이 중간에 잘린다)
        """
        self.model = model
        self.max_tokens = max_tokens

    # ------------------------------------------------------------
    # 필수 구현
    # ------------------------------------------------------------
    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        tools: list[ToolSpec] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        대화를 한 턴 진행한다.

        Args:
            messages: 대화 이력 (첫 메시지는 반드시 user).
            system: 시스템 프롬프트 (Agent 역할 정의).
            tools: 사용 가능한 도구 목록 (MCP 에서 수집한 ToolSpec).
            max_tokens: 이번 호출에만 적용할 최대 토큰 수.

        Returns:
            정규화된 LLMResponse.

        Raises:
            LLMError: 호출 실패 시 (한글 안내 메시지 포함).
        """

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """
        대화 응답을 텍스트 조각 단위로 스트리밍한다. (UI 실시간 표시용)

        Yields:
            생성되는 텍스트 조각.
        """

    @abstractmethod
    async def health_check(self) -> tuple[bool, str]:
        """
        Provider 연결 상태를 점검한다. (run_all.bat 헬스체크 / 설정 검증용)

        Returns:
            (성공 여부, 한글 상태 메시지)
        """

    # ------------------------------------------------------------
    # 공통 유틸
    # ------------------------------------------------------------
    async def close(self) -> None:
        """열려 있는 네트워크 연결을 정리한다. (기본 구현: 아무것도 하지 않음)"""
        return

    def _resolve_max_tokens(self, max_tokens: int | None) -> int:
        """호출별 max_tokens 가 없으면 인스턴스 기본값을 사용한다."""
        return max_tokens if max_tokens is not None else self.max_tokens

    @staticmethod
    def _validate_messages(messages: list[ChatMessage]) -> None:
        """대화 이력의 기본 규칙을 검증한다. (빈 목록 금지 / 첫 메시지는 user)"""
        if not messages:
            raise LLMError("대화 내용이 비어 있습니다. 최소 1개의 사용자 메시지가 필요합니다.")
        if messages[0].role != "user":
            raise LLMError("대화의 첫 메시지는 반드시 사용자(user) 메시지여야 합니다.")

    def __repr__(self) -> str:  # pragma: no cover - 디버깅용
        return f"<{type(self).__name__} provider={self.provider} model={self.model}>"
