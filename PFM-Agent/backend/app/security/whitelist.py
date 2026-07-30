"""
도메인 화이트리스트.

에이전트가 접속할 수 있는 주소를 제한한다.

사용처
------
1. `automation.open_browser` — 허용되지 않은 주소는 열지 않는다.
2. Verifier — 허용되지 않은 출처의 근거는 신뢰도에서 제외한다. (STEP 7)

설정 파일: `app/config/whitelist.json`
(비개발자 담당자가 직접 편집할 수 있도록 주석과 함께 구성)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("pfm-agent.whitelist")

#: 화이트리스트 설정 파일 경로
#: 이 파일: <루트>/backend/app/security/whitelist.py
WHITELIST_PATH: Path = Path(__file__).resolve().parents[1] / "config" / "whitelist.json"

#: 허용하는 URL 스킴 (file:// 등은 차단)
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})


@dataclass(frozen=True)
class WhitelistPolicy:
    """화이트리스트 정책."""

    allow_all: bool = False
    allowed_domains: tuple[str, ...] = field(default_factory=tuple)
    blocked_domains: tuple[str, ...] = field(default_factory=tuple)


def load_policy(path: Path | None = None) -> WhitelistPolicy:
    """
    화이트리스트 설정을 읽는다.

    파일이 없거나 형식이 잘못되면 **아무 도메인도 허용하지 않는** 정책을 반환한다.
    (설정 오류 시 열어주는 것보다 막는 쪽이 안전하다)
    """
    target = path or WHITELIST_PATH
    if not target.is_file():
        logger.warning("화이트리스트 파일이 없습니다: %s (모든 접속 차단)", target)
        return WhitelistPolicy()

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("화이트리스트를 읽지 못했습니다: %s (모든 접속 차단)", exc)
        return WhitelistPolicy()

    return WhitelistPolicy(
        allow_all=bool(raw.get("allow_all", False)),
        allowed_domains=tuple(
            str(item).strip().lower() for item in raw.get("allowed_domains", [])
        ),
        blocked_domains=tuple(
            str(item).strip().lower() for item in raw.get("blocked_domains", [])
        ),
    )


@lru_cache(maxsize=1)
def get_policy() -> WhitelistPolicy:
    """화이트리스트 정책 싱글턴."""
    return load_policy()


def reload_policy() -> WhitelistPolicy:
    """설정 파일을 다시 읽는다. (담당자가 파일을 수정한 뒤 호출)"""
    get_policy.cache_clear()
    return get_policy()


def extract_host(url: str) -> str:
    """
    URL 에서 호스트를 추출한다.

    스킴이 없으면 http 로 간주한다. (사용자가 'example.go.kr' 만 입력한 경우)
    """
    candidate = url.strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    return (parsed.hostname or "").lower()


def matches_domain(host: str, pattern: str) -> bool:
    """
    호스트가 패턴에 해당하는지 확인한다.

    'go.kr' 패턴은 'www.motie.go.kr' 같은 하위 도메인도 포함한다.
    단, 'evilgo.kr' 처럼 문자열만 겹치는 경우는 제외한다.
    """
    if not host or not pattern:
        return False
    return host == pattern or host.endswith(f".{pattern}")


def check_url(url: str, policy: WhitelistPolicy | None = None) -> tuple[bool, str]:
    """
    URL 접속 허용 여부를 판단한다.

    Args:
        url: 검사할 주소
        policy: 사용할 정책 (생략 시 설정 파일 값)

    Returns:
        (허용 여부, 사용자에게 보여줄 한글 사유)
    """
    active = policy or get_policy()

    if not url or not url.strip():
        return False, "주소가 비어 있습니다."

    candidate = url.strip()
    scheme = urlparse(
        candidate if "://" in candidate else f"http://{candidate}"
    ).scheme.lower()

    if scheme not in ALLOWED_SCHEMES:
        return False, (
            f"'{scheme}' 형식의 주소는 열 수 없습니다. "
            f"http 또는 https 주소만 사용할 수 있습니다."
        )

    host = extract_host(candidate)
    if not host:
        return False, f"주소를 해석할 수 없습니다: {url}"

    # 차단 목록이 우선한다.
    for pattern in active.blocked_domains:
        if matches_domain(host, pattern):
            return False, f"'{host}' 은(는) 차단된 도메인입니다."

    if active.allow_all:
        return True, f"'{host}' 접속을 허용합니다. (모든 도메인 허용 설정)"

    for pattern in active.allowed_domains:
        if matches_domain(host, pattern):
            return True, f"'{host}' 접속을 허용합니다."

    return False, (
        f"'{host}' 은(는) 허용 목록에 없어 접속할 수 없습니다.\n"
        f"필요하다면 담당자가 app/config/whitelist.json 에 도메인을 추가해야 합니다."
    )


def is_allowed(url: str, policy: WhitelistPolicy | None = None) -> bool:
    """URL 이 허용되는지 여부만 반환한다."""
    allowed, _ = check_url(url, policy)
    return allowed
