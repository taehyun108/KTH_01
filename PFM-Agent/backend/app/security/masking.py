"""
개인정보 마스킹.

보고서·로그·LLM 전송 내용에서 개인정보를 가린다.

마스킹 대상
-----------
  - 주민등록번호  : 900101-1234567 → 900101-*******
  - 휴대전화번호  : 010-1234-5678  → 010-****-5678
  - 이메일        : hong@posco.com → h***@posco.com
  - 카드번호      : 1234-5678-9012-3456 → ****-****-****-3456
  - 계좌번호(추정): 110-123-456789 → 110-***-******

⚠️ 왜 완전히 가리지 않는가
--------------------------
앞/뒤 일부를 남기면 사람이 "어떤 정보였는지" 식별할 수 있어 검토가 쉬워진다.
완전히 지우면 보고서 검토 시 무엇이 빠졌는지 알 수 없다.

⚠️ 한계
-------
정규식 기반이므로 100% 탐지를 보장하지 않는다.
**최종 확인은 사람이 해야 한다.** 마스킹은 사고를 줄이는 보조 장치다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: 마스킹 규칙 (이름, 정규식, 치환 함수)
_RRN_PATTERN = re.compile(r"\b(\d{6})[-\s]?([1-4]\d{6})\b")
_PHONE_PATTERN = re.compile(r"\b(01[016789])[-\s]?(\d{3,4})[-\s]?(\d{4})\b")
_EMAIL_PATTERN = re.compile(r"\b([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_CARD_PATTERN = re.compile(r"\b(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})\b")
_ACCOUNT_PATTERN = re.compile(r"\b(\d{2,3})-(\d{2,4})-(\d{5,7})\b")


@dataclass
class MaskingResult:
    """마스킹 결과."""

    text: str
    """마스킹이 적용된 텍스트"""

    counts: dict[str, int] = field(default_factory=dict)
    """종류별 마스킹 건수"""

    @property
    def total(self) -> int:
        """전체 마스킹 건수."""
        return sum(self.counts.values())

    @property
    def found_any(self) -> bool:
        """개인정보가 발견되었는지 여부."""
        return self.total > 0

    def summary(self) -> str:
        """사용자에게 보여줄 한글 요약."""
        if not self.found_any:
            return "개인정보가 발견되지 않았습니다."
        parts = [f"{name} {count}건" for name, count in self.counts.items() if count]
        return f"개인정보 {self.total}건을 가렸습니다: {', '.join(parts)}"


def _mask_rrn(match: re.Match[str]) -> str:
    """주민등록번호: 뒤 7자리를 가린다."""
    return f"{match.group(1)}-*******"


def _mask_phone(match: re.Match[str]) -> str:
    """휴대전화번호: 가운데를 가린다."""
    return f"{match.group(1)}-****-{match.group(3)}"


def _mask_email(match: re.Match[str]) -> str:
    """이메일: 아이디 첫 글자만 남긴다."""
    return f"{match.group(1)}***@{match.group(3)}"


def _mask_card(match: re.Match[str]) -> str:
    """카드번호: 마지막 4자리만 남긴다."""
    return f"****-****-****-{match.group(4)}"


def _mask_account(match: re.Match[str]) -> str:
    """계좌번호(추정): 앞자리만 남긴다."""
    return f"{match.group(1)}-{'*' * len(match.group(2))}-{'*' * len(match.group(3))}"


#: 적용 순서가 중요하다.
#: 주민번호·카드번호를 먼저 처리해야 계좌번호 규칙이 오탐하지 않는다.
_RULES: tuple[tuple[str, re.Pattern[str], Any], ...] = (
    ("주민등록번호", _RRN_PATTERN, _mask_rrn),
    ("카드번호", _CARD_PATTERN, _mask_card),
    ("휴대전화번호", _PHONE_PATTERN, _mask_phone),
    ("이메일", _EMAIL_PATTERN, _mask_email),
    ("계좌번호", _ACCOUNT_PATTERN, _mask_account),
)


def mask_text(text: str) -> MaskingResult:
    """
    텍스트에서 개인정보를 가린다.

    Args:
        text: 원본 텍스트

    Returns:
        MaskingResult (마스킹된 텍스트 + 종류별 건수)
    """
    if not text:
        return MaskingResult(text=text or "", counts={})

    result = text
    counts: dict[str, int] = {}

    for name, pattern, replacer in _RULES:
        result, count = pattern.subn(replacer, result)
        if count:
            counts[name] = counts.get(name, 0) + count

    return MaskingResult(text=result, counts=counts)


def mask_dict(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    """
    dict 안의 모든 문자열 값에 마스킹을 적용한다. (중첩 구조 포함)

    Returns:
        (마스킹된 dict, 종류별 건수)
    """
    total_counts: dict[str, int] = {}

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            masked = mask_text(value)
            for name, count in masked.counts.items():
                total_counts[name] = total_counts.get(name, 0) + count
            return masked.text
        if isinstance(value, dict):
            return {key: _walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    return _walk(data), total_counts


def contains_personal_info(text: str) -> bool:
    """개인정보가 포함되어 있는지 확인한다. (마스킹은 하지 않음)"""
    return mask_text(text).found_any
