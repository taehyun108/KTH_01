"""
STEP 6 검증: Perception & Executor 테스트.

⚠️ 환경 제약
   이 컨테이너는 **화면(디스플레이)이 없는 리눅스**라 실제 화면 캡처와
   마우스/키보드 조작을 실행할 수 없다. (배포 대상은 Windows)

   따라서 다음 두 가지를 나누어 검증한다.
     1. **순수 로직** (좌표 검증 / 키 조합 파싱 / 화이트리스트 / 텍스트 매칭)
        → 환경과 무관하므로 여기서 완전히 검증한다.
     2. **환경 의존 기능** (캡처/클릭)
        → 화면이 없을 때 "왜 안 되는지" 한글로 정확히 안내하는지 검증한다.
          (배포 환경에서 동작 여부는 실제 Windows PC 에서 확인해야 한다)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.executor import classify_action, extract_target, extract_url
from app.mcp_servers.automation_server import (
    BLOCKED_KEY_COMBOS,
    MAX_TEXT_LENGTH,
    AutomationMCPServer,
    ensure_key_allowed,
    parse_key_combo,
    validate_click,
    validate_text,
)
from app.mcp_servers.base_server import MCPToolError
from app.mcp_servers.screen_server import (
    ScreenMCPServer,
    bbox_center,
    prune_old_screenshots,
    score_text_match,
    validate_bbox,
    validate_region,
)
from app.security.whitelist import (
    WhitelistPolicy,
    check_url,
    extract_host,
    load_policy,
    matches_domain,
)

# ============================================================
# 1. 화면 영역 검증 (순수 로직)
# ============================================================


def test_validate_region_accepts_valid() -> None:
    """올바른 영역은 그대로 통과해야 한다."""
    assert validate_region([10, 20, 100, 50]) == (10, 20, 100, 50)
    assert validate_region(None) is None


@pytest.mark.parametrize(
    ("region", "keyword"),
    [
        ([10, 20, 100], "4개 값"),
        ([10, 20, 0, 50], "0보다 커야"),
        ([10, 20, 100, -5], "0보다 커야"),
        ([-1, 20, 100, 50], "0 이상"),
    ],
)
def test_validate_region_rejects_invalid(region: list[int], keyword: str) -> None:
    """잘못된 영역은 한글 안내와 함께 거부되어야 한다."""
    with pytest.raises(MCPToolError) as excinfo:
        validate_region(region)
    assert keyword in str(excinfo.value)


def test_validate_bbox() -> None:
    """OCR 영역 검증."""
    assert validate_bbox([0, 0, 100, 50]) == (0, 0, 100, 50)

    with pytest.raises(MCPToolError) as excinfo:
        validate_bbox([100, 0, 50, 50])  # x2 < x1
    assert "오른쪽" in str(excinfo.value)


def test_bbox_center() -> None:
    """영역 중심 좌표 계산."""
    assert bbox_center((0, 0, 100, 50)) == (50, 25)
    assert bbox_center((10, 20, 30, 40)) == (20, 30)


# ============================================================
# 2. UI 요소 매칭 (순수 로직)
# ============================================================


def test_score_text_match_exact() -> None:
    """완전 일치는 최고 점수여야 한다."""
    assert score_text_match("검색", "검색") == 1.0


def test_score_text_match_strips_ui_suffix() -> None:
    """'검색 버튼' 은 화면의 '검색' 과 매칭되어야 한다."""
    assert score_text_match("검색 버튼", "검색") == 1.0
    assert score_text_match("주소 입력창", "주소") == 1.0


def test_score_text_match_partial() -> None:
    """포함 관계는 중간 점수여야 한다."""
    assert score_text_match("검색", "통합검색") == 0.8


def test_score_text_match_unrelated() -> None:
    """관련 없는 텍스트는 0점이어야 한다."""
    assert score_text_match("검색", "로그인") == 0.0


def test_score_text_match_empty() -> None:
    """빈 문자열은 0점이어야 한다."""
    assert score_text_match("", "검색") == 0.0
    assert score_text_match("검색", "") == 0.0


def test_prune_old_screenshots(tmp_path: Path) -> None:
    """오래된 캡처 파일이 정리되어야 한다. (USB 용량 보호)"""
    import time

    for index in range(8):
        path = tmp_path / f"screen_{index}.png"
        path.write_bytes(b"fake")
        time.sleep(0.005)  # mtime 구분

    removed = prune_old_screenshots(tmp_path, keep=3)

    assert removed == 5
    assert len(list(tmp_path.glob("*.png"))) == 3
    # 최신 파일이 남아야 한다.
    assert (tmp_path / "screen_7.png").exists()


# ============================================================
# 3. 클릭 좌표 검증 (순수 로직)
# ============================================================


def test_validate_click_accepts_valid() -> None:
    """화면 범위 안의 좌표는 통과해야 한다."""
    assert validate_click(100, 200, "left", (1920, 1080)) == (100, 200, "left")
    assert validate_click(0, 0, "RIGHT", (1920, 1080)) == (0, 0, "right")


def test_validate_click_rejects_out_of_screen() -> None:
    """🔴 안전: 화면 밖 좌표는 거부되어야 한다. (오클릭 방지)"""
    with pytest.raises(MCPToolError) as excinfo:
        validate_click(3000, 200, "left", (1920, 1080))
    assert "화면 범위를 벗어납니다" in str(excinfo.value)
    assert "1920x1080" in str(excinfo.value)


def test_validate_click_rejects_negative() -> None:
    """음수 좌표는 거부되어야 한다."""
    with pytest.raises(MCPToolError) as excinfo:
        validate_click(-10, 200, "left", (1920, 1080))
    assert "0 이상" in str(excinfo.value)


def test_validate_click_rejects_bad_button() -> None:
    """알 수 없는 마우스 버튼은 거부되어야 한다."""
    with pytest.raises(MCPToolError) as excinfo:
        validate_click(10, 10, "double", (1920, 1080))
    assert "마우스 버튼" in str(excinfo.value)


def test_validate_click_skips_range_check_when_size_unknown() -> None:
    """화면 크기를 모르면 범위 검사를 건너뛴다."""
    assert validate_click(9999, 9999, "left", None) == (9999, 9999, "left")


# ============================================================
# 4. 키 입력 검증 (순수 로직)
# ============================================================


def test_parse_key_combo() -> None:
    """키 조합이 올바르게 분해되어야 한다."""
    assert parse_key_combo("enter") == ["enter"]
    assert parse_key_combo("ctrl+c") == ["ctrl", "c"]
    assert parse_key_combo("Ctrl + Shift + S") == ["ctrl", "shift", "s"]


def test_parse_key_combo_normalizes_aliases() -> None:
    """다양한 표현이 표준 이름으로 정규화되어야 한다."""
    assert parse_key_combo("Control+c") == ["ctrl", "c"]
    assert parse_key_combo("Return") == ["enter"]
    assert parse_key_combo("엔터") == ["enter"]


def test_parse_key_combo_rejects_empty() -> None:
    """빈 키는 거부되어야 한다."""
    with pytest.raises(MCPToolError) as excinfo:
        parse_key_combo("")
    assert "입력할 키를 지정" in str(excinfo.value)


@pytest.mark.parametrize(
    "combo", ["alt+f4", "ctrl+alt+delete", "ctrl+shift+escape", "win+l", "win+r"]
)
def test_dangerous_key_combos_blocked(combo: str) -> None:
    """🔴 안전: 시스템 종료/잠금 조합은 차단되어야 한다."""
    keys = parse_key_combo(combo)
    with pytest.raises(MCPToolError) as excinfo:
        ensure_key_allowed(keys)
    assert "시스템에 영향을 줄 수 있어" in str(excinfo.value)


def test_safe_key_combos_allowed() -> None:
    """일반적인 조합은 허용되어야 한다."""
    for combo in ["ctrl+c", "ctrl+v", "enter", "tab", "ctrl+s"]:
        ensure_key_allowed(parse_key_combo(combo))  # 예외가 없으면 통과


def test_blocked_combos_are_defined() -> None:
    """차단 목록이 비어 있지 않아야 한다."""
    assert len(BLOCKED_KEY_COMBOS) >= 5


# ============================================================
# 5. 텍스트 입력 검증 (순수 로직)
# ============================================================


def test_validate_text_accepts_normal() -> None:
    """일반 텍스트는 통과해야 한다."""
    assert validate_text("소듐이온배터리") == "소듐이온배터리"


def test_validate_text_rejects_empty() -> None:
    """빈 텍스트는 거부되어야 한다."""
    with pytest.raises(MCPToolError) as excinfo:
        validate_text("")
    assert "비어 있습니다" in str(excinfo.value)


def test_validate_text_rejects_too_long() -> None:
    """🔴 안전: 지나치게 긴 입력은 거부되어야 한다. (오작동 대량 입력 방지)"""
    with pytest.raises(MCPToolError) as excinfo:
        validate_text("가" * (MAX_TEXT_LENGTH + 1))
    assert "너무 깁니다" in str(excinfo.value)


# ============================================================
# 6. 화이트리스트 (순수 로직)
# ============================================================


def test_whitelist_file_loads() -> None:
    """실제 화이트리스트 파일이 정상 로드되어야 한다."""
    policy = load_policy()
    assert policy.allow_all is False
    assert "go.kr" in policy.allowed_domains


def test_extract_host() -> None:
    """URL 에서 호스트를 추출한다."""
    assert extract_host("https://www.motie.go.kr/path") == "www.motie.go.kr"
    assert extract_host("motie.go.kr") == "motie.go.kr"  # 스킴 생략
    assert extract_host("") == ""


def test_matches_domain_includes_subdomains() -> None:
    """상위 도메인 패턴은 하위 도메인을 포함해야 한다."""
    assert matches_domain("www.motie.go.kr", "go.kr") is True
    assert matches_domain("go.kr", "go.kr") is True


def test_matches_domain_rejects_lookalike() -> None:
    """🔴 보안: 문자열만 겹치는 유사 도메인은 차단되어야 한다."""
    assert matches_domain("evilgo.kr", "go.kr") is False
    assert matches_domain("go.kr.evil.com", "go.kr") is False


def test_check_url_allows_whitelisted() -> None:
    """허용 도메인은 통과해야 한다."""
    allowed, reason = check_url("https://www.motie.go.kr/policy")
    assert allowed is True
    assert "허용" in reason


def test_check_url_blocks_unlisted() -> None:
    """🔴 보안: 목록에 없는 도메인은 차단되어야 한다."""
    allowed, reason = check_url("https://evil.example.com")
    assert allowed is False
    assert "허용 목록에 없어" in reason
    assert "whitelist.json" in reason  # 해결 방법 안내


def test_check_url_blocks_non_http_scheme() -> None:
    """🔴 보안: file:// 같은 스킴은 차단되어야 한다."""
    allowed, reason = check_url("file:///etc/passwd")
    assert allowed is False
    assert "http 또는 https" in reason


def test_check_url_respects_blocked_list() -> None:
    """차단 목록이 허용 목록보다 우선해야 한다."""
    policy = WhitelistPolicy(
        allow_all=True, allowed_domains=("example.com",), blocked_domains=("bad.example.com",)
    )
    assert check_url("https://bad.example.com", policy)[0] is False
    assert check_url("https://good.example.com", policy)[0] is True


def test_check_url_empty_rejected() -> None:
    """빈 주소는 거부되어야 한다."""
    assert check_url("")[0] is False


def test_broken_whitelist_file_blocks_everything(tmp_path: Path) -> None:
    """
    🔴 보안: 설정 파일이 깨지면 **모두 차단**해야 한다.
    (설정 오류 시 열어주는 것보다 막는 쪽이 안전)
    """
    broken = tmp_path / "whitelist.json"
    broken.write_text("이건 JSON 이 아님", encoding="utf-8")

    policy = load_policy(broken)
    assert policy.allow_all is False
    assert policy.allowed_domains == ()
    assert check_url("https://www.motie.go.kr", policy)[0] is False


def test_missing_whitelist_file_blocks_everything(tmp_path: Path) -> None:
    """설정 파일이 없어도 모두 차단해야 한다."""
    policy = load_policy(tmp_path / "없는파일.json")
    assert check_url("https://www.motie.go.kr", policy)[0] is False


# ============================================================
# 7. Executor 계획 해석 (순수 로직)
# ============================================================


def test_extract_url_from_plan_step() -> None:
    """계획 문장에서 URL 을 찾아야 한다."""
    assert extract_url("https://www.motie.go.kr 에 접속한다") == "https://www.motie.go.kr"
    assert extract_url("검색 버튼을 클릭한다") is None


@pytest.mark.parametrize(
    ("step_text", "expected"),
    [
        ("https://www.motie.go.kr 에 접속한다", "browser"),
        ("브라우저를 열어 사이트에 들어간다", "browser"),
        ("검색 버튼을 클릭한다", "click"),
        ("'소듐이온배터리' 를 입력한다", "type"),
        ("자료를 정리해 보고서를 작성한다", "type"),
        ("결과를 검토한다", "none"),
    ],
)
def test_classify_action(step_text: str, expected: str) -> None:
    """계획 단계의 조작 종류가 올바르게 분류되어야 한다."""
    assert classify_action(step_text) == expected


def test_extract_target() -> None:
    """클릭 대상 설명이 추출되어야 한다."""
    assert "검색" in extract_target("검색 버튼을 클릭한다")


# ============================================================
# 8. 환경 의존 기능: 화면이 없을 때의 안내 (배포 환경 대비)
# ============================================================


async def test_capture_screen_gives_korean_guidance_without_display() -> None:
    """
    화면이 없는 환경에서는 캡처가 실패하되,
    **왜 안 되는지 한글로 안내**해야 한다.

    (배포 대상인 Windows PC 에서는 정상 동작한다)
    """
    server = ScreenMCPServer()
    try:
        result = await server.handle_call("capture_screen", {})
    except MCPToolError as exc:
        message = str(exc)
        assert "화면" in message
        # 원인과 해결 방향이 안내되어야 한다.
        assert any(word in message for word in ("원격", "설치", "잠금", "환경"))
    else:
        # 화면이 있는 환경이면 정상 캡처되어야 한다.
        assert "path" in result
        assert result["width"] > 0


async def test_click_gives_korean_guidance_without_display() -> None:
    """화면이 없으면 클릭도 한글 안내와 함께 실패해야 한다."""
    server = AutomationMCPServer()
    try:
        result = await server.handle_call("click", {"x": 10, "y": 10})
    except MCPToolError as exc:
        message = str(exc)
        assert any(word in message for word in ("화면", "설치", "실패"))
    else:
        assert result["x"] == 10


async def test_open_browser_blocks_unlisted_domain_before_opening() -> None:
    """
    🔴 보안 검증: 허용되지 않은 도메인은 **브라우저를 열기 전에** 차단되어야 한다.
    (화면 유무와 무관하게 항상 동작해야 하는 검사)
    """
    server = AutomationMCPServer()
    with pytest.raises(MCPToolError) as excinfo:
        await server.handle_call("open_browser", {"url": "https://evil.example.com"})
    assert "허용 목록에 없어" in str(excinfo.value)


async def test_key_press_blocks_dangerous_before_execution() -> None:
    """🔴 안전 검증: 위험한 키 조합은 실행 전에 차단되어야 한다."""
    server = AutomationMCPServer()
    with pytest.raises(MCPToolError) as excinfo:
        await server.handle_call("key_press", {"key": "alt+f4"})
    assert "시스템에 영향을 줄 수 있어" in str(excinfo.value)


async def test_unknown_tool_rejected() -> None:
    """없는 도구는 한글 안내와 함께 거부되어야 한다."""
    server = AutomationMCPServer()
    with pytest.raises(MCPToolError) as excinfo:
        await server.handle_call("shutdown_pc", {})
    assert "도구가 없습니다" in str(excinfo.value)
