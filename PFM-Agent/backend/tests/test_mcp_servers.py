"""
STEP 3 검증: 자체 MCP 서버 인프라 테스트.

각 MCP 서버를 **실제 별도 프로세스로 기동**해 stdio(JSON-RPC)로 통신하며 검증한다.
(모의 객체가 아니라 진짜 프로세스를 띄우므로 배포 환경과 동일한 경로를 검증한다)

검증 항목:
  - 5개 서버가 모두 독립 실행되고 도구 목록을 내보내는가
  - filesystem 도구가 실제로 읽기/쓰기/목록 동작을 수행하는가
  - 경로 탈출 공격이 차단되는가 (보안)
  - 미구현 스텁 도구가 명확한 한글 안내로 실패하는가
  - 레지스트리가 모든 도구를 수집하고 LLM ToolSpec 으로 변환하는가
  - 승인 게이트가 위험 도구를 차단하는가 (안전)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.base import ToolSpec
from app.mcp_client.client import (
    BACKEND_DIR,
    PROJECT_ROOT,
    MCPClient,
    MCPClientError,
    MCPServerConfig,
    build_server_env,
    load_mcp_config,
)
from app.mcp_client.tool_registry import (
    NAME_SEPARATOR,
    ApprovalDeniedError,
    RegisteredTool,
    ToolRegistry,
    split_qualified_name,
)
from app.mcp_servers.base_server import MCPToolError, safe_project_path
from app.mcp_servers.filesystem_server import FilesystemMCPServer

#: 실제 프로세스를 띄우는 테스트는 시간이 걸리므로 타임아웃을 넉넉히 잡는다.
CONNECT_TIMEOUT = 60.0


# ============================================================
# 1. 설정 로딩
# ============================================================


def test_config_loads_all_servers() -> None:
    """mcp_config.json 에 6개 서버가 등록되어 있어야 한다."""
    configs = load_mcp_config()
    assert set(configs) == {
        "filesystem",
        "screen",
        "automation",
        "rag",
        "report",
        "team",
    }


def test_automation_server_requires_approval() -> None:
    """위험 서버(automation)는 승인 필요로 등록되어야 한다."""
    configs = load_mcp_config()
    assert configs["automation"].require_approval is True
    # 나머지는 승인 불필요
    assert configs["filesystem"].require_approval is False


def test_python_command_resolves_to_venv_interpreter() -> None:
    """
    포터블 원칙: 'python' 은 시스템 PATH 가 아니라
    현재 가상환경의 인터프리터로 치환되어야 한다.
    """
    import sys

    config = MCPServerConfig(name="t", command="python", args=[])
    assert config.resolved_command() == sys.executable
    assert Path(config.resolved_command()).is_file()


def test_server_env_forces_utf8_and_pythonpath() -> None:
    """
    한글 Windows(cp949)에서 JSON-RPC 가 깨지지 않도록
    UTF-8 강제 및 PYTHONPATH 주입이 되어야 한다.
    """
    env = build_server_env()
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONPATH"] == str(BACKEND_DIR)


def test_config_path_is_inside_project() -> None:
    """설정 파일이 프로젝트 폴더 내부에 있어야 한다. (포터블 원칙)"""
    config_file = BACKEND_DIR / "app" / "mcp_servers" / "mcp_config.json"
    assert config_file.is_file()
    assert config_file.is_relative_to(PROJECT_ROOT)
    # JSON 형식 검증
    json.loads(config_file.read_text(encoding="utf-8"))


# ============================================================
# 2. 경로 보안 (프로세스 없이 직접 검증)
# ============================================================


@pytest.mark.parametrize(
    "malicious",
    [
        "../../../etc/passwd",
        "../../etc/shadow",
        "/etc/passwd",
        "./data/../../../../tmp/evil.txt",
    ],
)
def test_path_traversal_blocked(malicious: str) -> None:
    """프로젝트 폴더를 벗어나는 경로는 모두 차단되어야 한다."""
    with pytest.raises(MCPToolError) as excinfo:
        safe_project_path(malicious)
    assert "프로젝트 폴더 밖" in str(excinfo.value)


def test_relative_path_resolves_under_project_root() -> None:
    """정상적인 상대경로는 프로젝트 루트 기준으로 해석되어야 한다."""
    resolved = safe_project_path("./output/report.docx")
    assert resolved.is_relative_to(PROJECT_ROOT)
    assert resolved.name == "report.docx"


def test_empty_path_rejected() -> None:
    """빈 경로는 한글 안내와 함께 거부되어야 한다."""
    with pytest.raises(MCPToolError) as excinfo:
        safe_project_path("   ")
    assert "경로가 비어" in str(excinfo.value)


# ============================================================
# 3. 서버 클래스 단위 검증 (프로세스 없이)
# ============================================================


def test_filesystem_server_declares_three_tools() -> None:
    """filesystem 서버가 3개 도구를 선언해야 한다."""
    server = FilesystemMCPServer()
    assert set(server.tool_names()) == {"read_file", "write_file", "list_dir"}


def test_all_tools_have_meaningful_descriptions() -> None:
    """
    모든 도구는 LLM 이 사용 시점을 판단할 수 있도록
    충분한 설명을 가져야 한다.
    """
    from app.mcp_servers.automation_server import AutomationMCPServer
    from app.mcp_servers.rag_server import RagMCPServer
    from app.mcp_servers.report_server import ReportMCPServer
    from app.mcp_servers.screen_server import ScreenMCPServer
    from app.mcp_servers.team_server import TeamMCPServer

    servers = [
        FilesystemMCPServer(),
        ScreenMCPServer(),
        AutomationMCPServer(),
        RagMCPServer(),
        ReportMCPServer(),
        TeamMCPServer(),
    ]
    for server in servers:
        for tool in server.get_tools():
            assert tool.description, f"{server.name}.{tool.name} 설명 누락"
            assert len(tool.description) >= 20, f"{server.name}.{tool.name} 설명이 너무 짧음"
            assert tool.inputSchema.get("type") == "object", (
                f"{server.name}.{tool.name} 의 inputSchema 가 object 가 아님"
            )


# ============================================================
# 4. 실제 프로세스 기동 통합 테스트
# ============================================================


@pytest.fixture
async def mcp_client():
    """모든 MCP 서버를 실제 프로세스로 기동한 클라이언트."""
    client = MCPClient.from_config(timeout=CONNECT_TIMEOUT)
    async with client:
        yield client


async def test_all_servers_start_successfully(mcp_client: MCPClient) -> None:
    """6개 서버가 모두 독립 프로세스로 기동되어야 한다."""
    assert mcp_client.failed_servers == {}, f"기동 실패: {mcp_client.failed_servers}"
    assert set(mcp_client.connected_servers) == {
        "filesystem",
        "screen",
        "automation",
        "rag",
        "report",
        "team",
    }


async def test_all_tools_collected(mcp_client: MCPClient) -> None:
    """모든 서버의 도구가 수집되어야 한다. (3+4+4+2+2+4 = 19)"""
    assert mcp_client.total_tool_count() == 19


async def test_filesystem_write_then_read(mcp_client: MCPClient, tmp_path: Path) -> None:
    """write_file 로 저장한 내용을 read_file 로 다시 읽을 수 있어야 한다."""
    # 프로젝트 내부 경로만 허용되므로 ./data 하위 임시 파일을 사용한다.
    rel_path = "./data/_test_mcp_roundtrip.txt"
    content = "소듐이온배터리 정책동향 테스트 내용\n한글 인코딩 확인 ✅"

    write_result = await mcp_client.call_tool(
        "filesystem", "write_file", {"path": rel_path, "content": content}
    )
    assert not write_result.is_error, write_result.text

    read_result = await mcp_client.call_tool("filesystem", "read_file", {"path": rel_path})
    assert not read_result.is_error, read_result.text
    assert read_result.structured is not None
    assert read_result.structured["content"] == content

    # 정리
    (PROJECT_ROOT / "data" / "_test_mcp_roundtrip.txt").unlink(missing_ok=True)


async def test_filesystem_list_dir(mcp_client: MCPClient) -> None:
    """list_dir 이 프로젝트 루트의 항목을 나열해야 한다."""
    result = await mcp_client.call_tool("filesystem", "list_dir", {"path": "."})
    assert not result.is_error, result.text
    assert result.structured is not None
    names = {entry["name"] for entry in result.structured["entries"]}
    assert "backend" in names
    assert "README.md" in names


async def test_filesystem_blocks_traversal_over_rpc(mcp_client: MCPClient) -> None:
    """
    실제 JSON-RPC 경로로도 경로 탈출이 차단되어야 한다.
    (서버 프로세스 안에서 검증이 동작하는지 확인)
    """
    result = await mcp_client.call_tool(
        "filesystem", "read_file", {"path": "../../../etc/passwd"}
    )
    assert result.is_error is True
    assert "프로젝트 폴더 밖" in result.text


async def test_filesystem_missing_file_error(mcp_client: MCPClient) -> None:
    """없는 파일을 읽으면 한글 안내가 나와야 한다."""
    result = await mcp_client.call_tool(
        "filesystem", "read_file", {"path": "./data/존재하지않는파일.txt"}
    )
    assert result.is_error is True
    assert "찾을 수 없습니다" in result.text


async def test_input_schema_validation_over_rpc(mcp_client: MCPClient) -> None:
    """필수 인자를 빠뜨리면 MCP SDK 의 스키마 검증이 막아야 한다."""
    result = await mcp_client.call_tool("filesystem", "read_file", {})
    assert result.is_error is True


@pytest.mark.parametrize(
    ("server", "tool", "arguments"),
    [
        ("screen", "capture_screen", {}),
        ("automation", "click", {"x": 10, "y": 20}),
    ],
)
async def test_environment_dependent_tools_give_guidance(
    mcp_client: MCPClient, server: str, tool: str, arguments: dict[str, Any]
) -> None:
    """
    화면이 필요한 도구(STEP 6 구현 완료)는 이 환경(화면 없음)에서 실패하되,
    **왜 안 되는지 한글로 안내**해야 한다. 서버는 계속 살아 있어야 한다.

    (배포 대상인 Windows PC 에서는 정상 동작한다)
    """
    result = await mcp_client.call_tool(server, tool, arguments)

    if result.is_error:
        assert any(
            word in result.text for word in ("화면", "설치", "환경", "실패")
        ), f"안내 문구가 불충분합니다: {result.text}"
        # 서버가 살아 있는지 확인 (다음 호출이 정상 동작해야 함)
        follow_up = await mcp_client.call_tool(server, tool, arguments)
        assert follow_up is not None
    else:
        # 화면이 있는 환경이면 정상 동작해야 한다.
        assert result.structured is not None


async def test_rag_search_works_without_model(mcp_client: MCPClient) -> None:
    """
    🔴 폐쇄망 대비: 임베딩 모델이 없어도 사내 문서 검색이 동작해야 한다.
    (키워드 검색으로 자동 대체되며, 어떤 방식인지 결과에 표시된다)
    """
    result = await mcp_client.call_tool(
        "rag", "search_internal_docs", {"query": "소듐이온배터리 정책"}
    )

    assert result.is_error is False, result.text
    assert result.structured is not None
    # 색인이 비어 있어도 오류가 아니라 안내를 반환해야 한다.
    assert "method" in result.structured
    assert result.structured["method"] in {"vector", "keyword"}


async def test_rag_add_document_and_search(mcp_client: MCPClient) -> None:
    """문서를 색인에 추가한 뒤 검색으로 찾을 수 있어야 한다."""
    doc_path = PROJECT_ROOT / "data" / "_test_rag_doc.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "소듐이온배터리는 리튬이온 대비 원가가 낮아 ESS 분야에서 주목받는다.",
        encoding="utf-8",
    )

    try:
        added = await mcp_client.call_tool(
            "rag", "add_document", {"path": "./data/_test_rag_doc.md"}
        )
        assert added.is_error is False, added.text
        assert (added.structured or {}).get("chunks_added", 0) >= 1

        found = await mcp_client.call_tool(
            "rag", "search_internal_docs", {"query": "소듐이온배터리 원가"}
        )
        assert found.is_error is False, found.text
        sources = [item["source"] for item in (found.structured or {}).get("results", [])]
        assert any("_test_rag_doc.md" in source for source in sources)
    finally:
        doc_path.unlink(missing_ok=True)
        (PROJECT_ROOT / "data" / "rag_index.json").unlink(missing_ok=True)


async def test_rag_masks_personal_info(mcp_client: MCPClient) -> None:
    """🔴 보안: 검색 결과의 개인정보가 가려져야 한다."""
    doc_path = PROJECT_ROOT / "data" / "_test_rag_privacy.md"
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        "담당자 연락처는 010-1234-5678 이고 이메일은 hong@posco.com 입니다.",
        encoding="utf-8",
    )

    try:
        await mcp_client.call_tool(
            "rag", "add_document", {"path": "./data/_test_rag_privacy.md"}
        )
        found = await mcp_client.call_tool(
            "rag", "search_internal_docs", {"query": "담당자 연락처"}
        )

        combined = " ".join(
            item["content"] for item in (found.structured or {}).get("results", [])
        )
        if combined:  # 검색 결과가 있을 때만 검증
            assert "010-1234-5678" not in combined
            assert "hong@posco.com" not in combined
    finally:
        doc_path.unlink(missing_ok=True)
        (PROJECT_ROOT / "data" / "rag_index.json").unlink(missing_ok=True)


async def test_unknown_server_raises(mcp_client: MCPClient) -> None:
    """등록되지 않은 서버 호출은 한글 안내와 함께 실패해야 한다."""
    with pytest.raises(MCPClientError) as excinfo:
        await mcp_client.call_tool("email", "send_mail", {})
    assert "연결되어 있지 않습니다" in str(excinfo.value)


# ============================================================
# 5. 도구 레지스트리 (LLM 연결부)
# ============================================================


def test_qualified_name_uses_double_underscore() -> None:
    """
    LLM 도구 이름은 점(.)을 쓸 수 없으므로 `서버__도구` 형식이어야 한다.
    (표시용 이름만 점을 사용)
    """
    tool = RegisteredTool(
        server="filesystem", name="read_file", description="d", input_schema={}
    )
    assert tool.qualified_name == "filesystem__read_file"
    assert tool.display_name == "filesystem.read_file"
    assert "." not in tool.qualified_name


def test_split_qualified_name() -> None:
    """정규화된 이름을 서버/도구로 되돌릴 수 있어야 한다."""
    assert split_qualified_name("filesystem__read_file") == ("filesystem", "read_file")
    with pytest.raises(ValueError):
        split_qualified_name("read_file")


async def test_registry_collects_all_tools(mcp_client: MCPClient) -> None:
    """레지스트리가 모든 서버의 도구를 수집해야 한다."""
    registry = ToolRegistry(mcp_client)
    count = registry.refresh()
    assert count == 19
    names = {tool.qualified_name for tool in registry.tools}
    assert "filesystem__read_file" in names
    assert "automation__click" in names
    # GUI 자동 조작 루프가 화면 상태를 읽는 데 쓰는 도구
    assert "screen__list_ui_elements" in names
    # 팀 대화방 공유 도구 (Agent 가 결과를 팀에 전달)
    assert "team__post_message" in names


async def test_registry_converts_to_llm_tool_specs(mcp_client: MCPClient) -> None:
    """수집한 도구가 LLM ToolSpec 으로 변환되어야 한다."""
    registry = ToolRegistry(mcp_client)
    registry.refresh()
    specs = registry.to_tool_specs()

    assert len(specs) == 19
    assert all(isinstance(spec, ToolSpec) for spec in specs)

    # LLM API 의 도구 이름 규칙 검증: ^[a-zA-Z0-9_-]{1,64}$
    import re

    pattern = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
    for spec in specs:
        assert pattern.match(spec.name), f"LLM 도구 이름 규칙 위반: {spec.name}"
        assert spec.input_schema.get("type") == "object"


async def test_registry_marks_approval_tools(mcp_client: MCPClient) -> None:
    """automation 서버의 도구는 승인 필요로 표시되어야 한다."""
    registry = ToolRegistry(mcp_client)
    registry.refresh()

    approval_tools = {tool.qualified_name for tool in registry.approval_required_tools()}
    assert approval_tools == {
        "automation__click",
        "automation__type_text",
        "automation__key_press",
        "automation__open_browser",
    }

    # 승인 필요 도구의 설명에 경고가 포함되어야 한다.
    spec = next(s for s in registry.to_tool_specs() if s.name == "automation__click")
    assert "승인" in spec.description


async def test_registry_runs_safe_tool_without_approval(mcp_client: MCPClient) -> None:
    """승인이 필요 없는 도구는 콜백 없이도 실행되어야 한다."""
    registry = ToolRegistry(mcp_client)
    registry.refresh()

    result = await registry.call("filesystem__list_dir", {"path": "."})
    assert not result.is_error, result.text


async def test_registry_blocks_dangerous_tool_without_approval_gate(
    mcp_client: MCPClient,
) -> None:
    """
    🔴 안전 검증: 승인 콜백이 없으면 위험 도구는 **실행되지 않아야** 한다.
    (안전 우선 기본값 — 무단 실행 방지)
    """
    registry = ToolRegistry(mcp_client, approval_callback=None)
    registry.refresh()

    with pytest.raises(ApprovalDeniedError) as excinfo:
        await registry.call("automation__click", {"x": 100, "y": 200})
    assert "승인이 필요한 도구" in str(excinfo.value)


async def test_registry_respects_user_denial(mcp_client: MCPClient) -> None:
    """🔴 안전 검증: 사용자가 거절하면 도구가 실행되지 않아야 한다."""
    asked: list[str] = []

    async def deny(tool: RegisteredTool, arguments: dict[str, Any]) -> bool:
        asked.append(tool.display_name)
        return False

    registry = ToolRegistry(mcp_client, approval_callback=deny)
    registry.refresh()

    with pytest.raises(ApprovalDeniedError) as excinfo:
        await registry.call("automation__type_text", {"text": "비밀번호"})

    assert asked == ["automation.type_text"]  # 승인 요청이 실제로 발생
    assert "거절" in str(excinfo.value)


async def test_registry_proceeds_on_user_approval(mcp_client: MCPClient) -> None:
    """
    사용자가 승인하면 도구 호출이 서버까지 전달되어야 한다.
    (automation 은 아직 스텁이므로 '미구현' 오류가 나오면 전달된 것)
    """
    async def approve(tool: RegisteredTool, arguments: dict[str, Any]) -> bool:
        return True

    registry = ToolRegistry(mcp_client, approval_callback=approve)
    registry.refresh()

    result = await registry.call("automation__click", {"x": 1, "y": 2})
    # 승인 게이트를 통과해 automation 서버까지 도달했는지 확인한다.
    # (이 환경은 화면이 없어 실패하지만, 실패 사유가 '승인'이 아니어야 한다)
    assert "승인" not in result.text
    assert "거절" not in result.text


async def test_registry_global_approval_switch(mcp_client: MCPClient) -> None:
    """.env 의 REQUIRE_APPROVAL=false 면 승인 게이트를 건너뛴다. (개발 편의)"""
    registry = ToolRegistry(mcp_client, approval_callback=None, require_approval=False)
    registry.refresh()

    result = await registry.call("automation__click", {"x": 1, "y": 2})
    # 승인 요청 없이 서버까지 도달해야 한다.
    assert "승인" not in result.text
    assert "거절" not in result.text


async def test_registry_logs_actions(mcp_client: MCPClient) -> None:
    """실행 기록 콜백이 호출되어야 한다. (STEP 5 Action Logger 연결점)"""
    logged: list[tuple[str, bool]] = []

    async def log(
        tool: RegisteredTool, arguments: dict[str, Any], output: str, ok: bool
    ) -> None:
        logged.append((tool.display_name, ok))

    registry = ToolRegistry(mcp_client, action_log_callback=log)
    registry.refresh()

    await registry.call("filesystem__list_dir", {"path": "."})
    assert logged == [("filesystem.list_dir", True)]


async def test_registry_unknown_tool_lists_available(mcp_client: MCPClient) -> None:
    """없는 도구를 부르면 사용 가능한 도구 목록을 안내해야 한다."""
    registry = ToolRegistry(mcp_client)
    registry.refresh()

    with pytest.raises(MCPClientError) as excinfo:
        await registry.call("filesystem__delete_everything", {})
    assert "찾을 수 없습니다" in str(excinfo.value)
    assert "filesystem__read_file" in str(excinfo.value)


async def test_registry_summary_is_readable(mcp_client: MCPClient) -> None:
    """등록 현황 요약이 한글로 표시되어야 한다."""
    registry = ToolRegistry(mcp_client)
    registry.refresh()

    summary = registry.summary()
    assert "MCP 도구 19개 등록됨" in summary
    assert "automation (승인 필요)" in summary
    assert NAME_SEPARATOR not in summary  # 표시용은 점 표기를 사용


# ============================================================
# stdout 보호 (JSON-RPC 채널 오염 방지)
# ============================================================


def test_protect_stdout_redirects_prints(capsys: pytest.CaptureFixture[str]) -> None:
    """
    보호 구간 안의 stdout 출력이 stderr 로 가야 한다.

    MCP 의 stdout 은 JSON-RPC 전용 통신선이다. 외부 라이브러리(PaddleOCR 등)가
    여기에 진행 상황을 찍으면 **연결 자체가 깨진다.**
    (실제로 "Failed to parse JSONRPC message from server" 로 확인된 문제)
    """
    from app.mcp_servers.base_server import protect_stdout

    with protect_stdout():
        print("download https://example.com/model.tar")

    captured = capsys.readouterr()
    assert captured.out == "", "stdout 이 오염되었다 (JSON-RPC 깨짐)"
    assert "download https://example.com/model.tar" in captured.err


def test_protect_stdout_restores_after_exit(capsys: pytest.CaptureFixture[str]) -> None:
    """보호 구간을 벗어나면 stdout 이 원래대로 돌아와야 한다."""
    from app.mcp_servers.base_server import protect_stdout

    with protect_stdout():
        print("안쪽")
    print("바깥쪽")

    captured = capsys.readouterr()
    assert "바깥쪽" in captured.out
    assert "안쪽" not in captured.out


def test_protect_stdout_restores_on_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """예외가 나도 stdout 을 반드시 복구해야 한다."""
    from app.mcp_servers.base_server import protect_stdout

    with pytest.raises(RuntimeError), protect_stdout():
        print("실패 직전 출력")
        raise RuntimeError("도구 실패")

    print("복구 확인")
    captured = capsys.readouterr()
    assert "복구 확인" in captured.out
    assert "실패 직전 출력" not in captured.out


async def test_tool_call_output_does_not_pollute_protocol(
    mcp_client: MCPClient,
) -> None:
    """
    도구가 실제로 stdout 에 출력해도 JSON-RPC 응답이 정상이어야 한다.

    보호막이 실제 서버 프로세스에서 동작하는지 확인한다.
    (filesystem 도구를 연달아 호출해 통신이 계속 살아 있는지 본다)
    """
    for _ in range(3):
        result = await mcp_client.call_tool("filesystem", "list_dir", {"path": "."})
        assert not result.is_error
        assert result.structured is not None
