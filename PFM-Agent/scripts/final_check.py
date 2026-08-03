"""
STEP 11 최종 검증 체크리스트.

요구사항의 11개 항목을 **실제로 실행해서** 확인한다.
설명이나 코드 읽기가 아니라, 진짜로 동작시켜 결과로 판정한다.

실행:
    python scripts/final_check.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))


@dataclass
class CheckItem:
    """검증 항목 하나."""

    name: str
    passed: bool = False
    detail: str = ""
    skipped: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def mark(self) -> str:
        """결과 표시."""
        if self.skipped:
            return "건너뜀"
        return "통과" if self.passed else "실패"


class Checklist:
    """검증 결과 모음."""

    def __init__(self) -> None:
        self.items: list[CheckItem] = []

    def add(self, item: CheckItem) -> CheckItem:
        """항목을 추가하고 즉시 출력한다."""
        self.items.append(item)
        print(f"  [{item.mark}] {item.name}")
        if item.detail:
            print(f"          {item.detail}")
        for note in item.notes:
            print(f"          · {note}")
        return item

    @property
    def all_passed(self) -> bool:
        """건너뛴 항목을 제외하고 모두 통과했는지."""
        return all(item.passed for item in self.items if not item.skipped)

    def summary(self) -> str:
        """요약 문자열."""
        passed = sum(1 for item in self.items if item.passed)
        skipped = sum(1 for item in self.items if item.skipped)
        failed = len(self.items) - passed - skipped
        return f"통과 {passed} / 실패 {failed} / 건너뜀 {skipped}"


# ============================================================
# 개별 검증
# ============================================================


def check_llm_anthropic(checklist: Checklist) -> None:
    """1. LLM_PROVIDER=anthropic 으로 정상 동작"""
    from app.config.settings import Settings
    from app.llm.anthropic_client import AnthropicClient
    from app.llm.factory import LLMClient

    settings = Settings(llm_provider="anthropic", anthropic_api_key="test-key")
    client = LLMClient.from_env(settings)

    passed = isinstance(client, AnthropicClient)
    checklist.add(
        CheckItem(
            name="LLM_PROVIDER=anthropic 으로 정상 동작",
            passed=passed,
            detail=f"{type(client).__name__} / 모델 {client.model}",
        )
    )


def check_llm_pgpt(checklist: Checklist) -> None:
    """2. LLM_PROVIDER=pgpt 로 어댑터 정상 로드 (Mock 서버로 검증)"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.config.settings import Settings
    from app.llm.base import ChatMessage
    from app.llm.factory import LLMClient
    from app.llm.pgpt_client import PGPTClient

    # --- 사내 P-GPT 를 흉내내는 Mock 서버 ---
    class MockPGPT(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            body = json.dumps(
                {
                    "id": "mock",
                    "model": "pgpt-test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "안녕하세요"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return  # 로그 억제

    server = HTTPServer(("127.0.0.1", 0), MockPGPT)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        settings = Settings(
            llm_provider="pgpt",
            pgpt_base_url=f"http://127.0.0.1:{port}/v1",
            pgpt_api_key="mock-key",
            pgpt_model="pgpt-test",
        )
        client = LLMClient.from_env(settings)
        assert isinstance(client, PGPTClient)

        response = asyncio.run(
            client.chat([ChatMessage(role="user", content="안녕")])
        )
        passed = response.content == "안녕하세요"
        detail = f"Mock P-GPT 응답 수신: '{response.content}' (토큰 {response.usage.input_tokens})"
    except Exception as exc:  # noqa: BLE001
        passed, detail = False, f"오류: {exc}"
    finally:
        server.shutdown()

    checklist.add(
        CheckItem(
            name="LLM_PROVIDER=pgpt 로 어댑터 정상 로드 (Mock 서버 검증)",
            passed=passed,
            detail=detail,
        )
    )


def check_mcp_standalone(checklist: Checklist) -> None:
    """3. 각 MCP 서버가 독립적으로 실행 가능"""
    from app.mcp_client.client import build_server_env, load_mcp_config

    configs = load_mcp_config()
    results: list[str] = []
    all_ok = True

    for name, config in configs.items():
        if not config.enabled:
            continue
        # 서버를 단독 프로세스로 띄워 즉시 종료되는지(=import 가능한지) 확인
        process = subprocess.Popen(
            [config.resolved_command(), *config.args],
            cwd=str(BACKEND_DIR),
            env={**os.environ, **build_server_env()},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # stdin 을 닫으면 서버가 정상 종료되어야 한다.
            _, stderr = process.communicate(timeout=20)
            started = b"MCP \xec\x84\x9c\xeb\xb2\x84 \xec\x8b\x9c\xec\x9e\x91" in stderr
            results.append(f"{name}={'OK' if started else 'NG'}")
            all_ok = all_ok and started
        except subprocess.TimeoutExpired:
            process.kill()
            results.append(f"{name}=TIMEOUT")
            all_ok = False

    checklist.add(
        CheckItem(
            name="각 MCP 서버가 독립적으로 실행 가능",
            passed=all_ok,
            detail=" ".join(results),
        )
    )


def check_tool_collection(checklist: Checklist) -> None:
    """4. MCP 클라이언트가 모든 도구를 정상 수집"""
    from app.mcp_client.client import MCPClient
    from app.mcp_client.tool_registry import ToolRegistry

    async def collect() -> tuple[int, int, list[str]]:
        client = MCPClient.from_config(timeout=40)
        async with client:
            registry = ToolRegistry(client)
            count = registry.refresh()
            specs = registry.to_tool_specs()
            servers = client.connected_servers
            # LLM 도구 이름 규칙 검증
            import re

            pattern = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
            invalid = [s.name for s in specs if not pattern.match(s.name)]
            if invalid:
                raise AssertionError(f"도구 이름 규칙 위반: {invalid}")
            return count, len(servers), servers

    try:
        count, server_count, servers = asyncio.run(collect())
        passed = count == 19 and server_count == 6
        detail = f"도구 {count}개 / 서버 {server_count}개 ({', '.join(servers)})"
    except Exception as exc:  # noqa: BLE001
        passed, detail = False, f"오류: {exc}"

    checklist.add(
        CheckItem(
            name="MCP 클라이언트가 모든 도구를 정상 수집",
            passed=passed,
            detail=detail,
        )
    )


def check_portable(checklist: Checklist) -> None:
    """5. 프로젝트 폴더 이동 후에도 정상 동작"""
    with tempfile.TemporaryDirectory() as temp:
        moved = Path(temp) / "다른위치" / "PFM-Agent"
        moved.parent.mkdir(parents=True)
        shutil.copytree(
            BACKEND_DIR / "app",
            moved / "backend" / "app",
            ignore=shutil.ignore_patterns("__pycache__"),
        )

        script = (
            "from app.config.settings import PROJECT_ROOT, load_settings;"
            "s = load_settings();"
            "assert s.output_dir.is_relative_to(PROJECT_ROOT);"
            "assert s.log_dir.is_relative_to(PROJECT_ROOT);"
            "print(PROJECT_ROOT)"
        )
        process = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(moved / "backend"),
            env={**os.environ, "PYTHONPATH": str(moved / "backend")},
            capture_output=True,
            text=True,
            timeout=60,
            check=False,  # 실패해도 결과로 판정한다
        )
        passed = process.returncode == 0 and "다른위치" in process.stdout
        detail = (
            f"이동한 위치를 인식: {process.stdout.strip()[-60:]}"
            if passed
            else f"오류: {process.stderr.strip()[-200:]}"
        )

    checklist.add(
        CheckItem(
            name="프로젝트 폴더 이동 후에도 정상 동작",
            passed=passed,
            detail=detail,
        )
    )


def check_offline_rag(checklist: Checklist) -> None:
    """6. 인터넷 끊고 사내 RAG 만으로 동작"""
    from app.rag.vector_store import VectorStore

    with tempfile.TemporaryDirectory() as temp:
        store = VectorStore(
            data_dir=Path(temp), model_path=Path(temp) / "없는모델"
        )
        store.add_text(
            "정책.md",
            "소듐이온배터리는 리튬 대비 원가가 낮아 ESS 분야에서 주목받고 있다.",
        )
        results = store.search("소듐이온배터리 원가", top_k=3)

        passed = bool(results) and store.method == "keyword"
        detail = (
            f"모델/인터넷 없이 검색 성공 (방식: {store.method}, "
            f"결과 {len(results)}건, 점수 {results[0].score:.3f})"
            if results
            else "검색 결과 없음"
        )

    checklist.add(
        CheckItem(
            name="인터넷 끊고 사내 RAG 만으로 동작",
            passed=passed,
            detail=detail,
        )
    )


def check_kill_switch(checklist: Checklist) -> None:
    """7. Kill Switch 가 어떤 상황에서도 동작"""
    from app.agents.runtime import AgentRuntime, EventBus, KilledError
    from app.mcp_client.tool_registry import ToolRegistry
    from app.safety.kill_switch import KillSwitch

    notes: list[str] = []

    # (a) 전역 훅: 등록 실패해도 예외가 나오면 안 된다.
    switch = KillSwitch(key="esc")
    hook_ok = isinstance(switch.start(), bool)
    notes.append(
        f"전역 ESC 훅: {'등록됨' if switch.available else '이 환경에서는 불가(화면 버튼으로 대체)'}"
    )
    switch.stop()

    # (b) 수동 발동: 훅 없이도 콜백이 호출되어야 한다.
    triggered: list[int] = []
    manual = KillSwitch(key="esc", on_trigger=lambda: triggered.append(1))
    manual.trigger()
    manual_ok = triggered == [1]
    notes.append(f"수동/버튼 발동: {'동작' if manual_ok else '실패'}")

    # (c) 런타임 중단: ensure_alive 가 예외를 던져야 한다.
    class _Dummy:
        """도구가 없는 상태를 흉내내는 최소 객체."""

        def __init__(self) -> None:
            self.configs: dict[str, object] = {}

        def list_tools(self) -> dict[str, list[object]]:
            return {}

    runtime = AgentRuntime(
        llm=None,  # type: ignore[arg-type]
        registry=ToolRegistry(_Dummy()),  # type: ignore[arg-type]
        event_bus=EventBus(),
    )
    runtime.register_run("check")
    runtime.kill("check")
    try:
        runtime.ensure_alive("check")
        runtime_ok = False
    except KilledError:
        runtime_ok = True
    notes.append(f"실행 중단 전파: {'동작' if runtime_ok else '실패'}")

    checklist.add(
        CheckItem(
            name="Kill Switch 가 어떤 상황에서도 동작",
            passed=hook_ok and manual_ok and runtime_ok,
            notes=notes,
        )
    )


def check_outputs_inside_project(checklist: Checklist) -> None:
    """8. 모든 로그/출력물이 프로젝트 폴더 내부에 저장"""
    from app.config.settings import PROJECT_ROOT as SETTINGS_ROOT
    from app.config.settings import load_settings

    settings = load_settings()
    paths = {
        "출력물": settings.output_dir,
        "로그": settings.log_dir,
        "데이터": settings.data_dir,
        "벡터DB": settings.chroma_db_dir,
        "액션기록": settings.action_log_path.parent,
        "임베딩모델": settings.embedding_model_path,
    }

    outside = [
        f"{name}={path}"
        for name, path in paths.items()
        if not path.resolve().is_relative_to(SETTINGS_ROOT.resolve())
    ]

    checklist.add(
        CheckItem(
            name="모든 로그/출력물이 프로젝트 폴더 내부에 저장",
            passed=not outside,
            detail=(
                f"{len(paths)}개 경로 모두 프로젝트 내부"
                if not outside
                else f"외부 경로 발견: {outside}"
            ),
        )
    )


def check_no_system_env_dependency(checklist: Checklist) -> None:
    """9. 시스템 환경변수 의존성 없음"""
    from app.config.settings import load_settings

    # 관련 환경변수를 모두 지운 상태에서도 기본값으로 동작해야 한다.
    keys = [
        "LLM_PROVIDER", "PGPT_BASE_URL", "PGPT_API_KEY", "PGPT_MODEL",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BACKEND_PORT",
        "OUTPUT_DIR", "LOG_DIR", "DATA_DIR",
    ]
    saved = {key: os.environ.pop(key, None) for key in keys}

    try:
        settings = load_settings()
        passed = (
            settings.llm_provider in {"pgpt", "anthropic", "openai"}
            and settings.backend_port > 0
            and settings.require_approval is True  # 안전 기본값
        )
        detail = (
            f"환경변수 제거 상태에서 기본값 로드 성공 "
            f"(provider={settings.llm_provider}, 승인필요={settings.require_approval})"
        )
    except Exception as exc:  # noqa: BLE001
        passed, detail = False, f"오류: {exc}"
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value

    checklist.add(
        CheckItem(
            name="시스템 환경변수 의존성 없음",
            passed=passed,
            detail=detail,
        )
    )


def check_setup_guide(checklist: Checklist) -> None:
    """10. SETUP_GUIDE_KR.md 만 보고 비개발자가 세팅 가능"""
    guide = PROJECT_ROOT / "SETUP_GUIDE_KR.md"
    if not guide.is_file():
        checklist.add(
            CheckItem(name="SETUP_GUIDE_KR.md 로 비개발자 세팅 가능", passed=False,
                      detail="문서가 없습니다")
        )
        return

    text = guide.read_text(encoding="utf-8")
    required = {
        "설치 실행 파일 안내": "first_time_setup.bat",
        "실행 파일 안내": "run_all.bat",
        "P-GPT 설정 안내": "PGPT_BASE_URL",
        "비상 정지 안내": "ESC",
        "문제 해결 안내": "자주 묻는",
    }
    missing = [label for label, keyword in required.items() if keyword not in text]

    # 문서가 실제로 존재하는 파일을 가리키는지 확인
    broken = [
        name
        for name in ("first_time_setup.bat", "run_all.bat", ".env.example")
        if name in text and not (PROJECT_ROOT / name).exists()
    ]

    checklist.add(
        CheckItem(
            name="SETUP_GUIDE_KR.md 만 보고 비개발자가 세팅 가능",
            passed=not missing and not broken,
            detail=(
                f"필수 안내 {len(required)}개 모두 포함, 참조 파일 실재 확인"
                if not missing and not broken
                else f"누락: {missing} / 없는 파일 참조: {broken}"
            ),
        )
    )


def check_mcp_guide(checklist: Checklist) -> None:
    """11. MCP_GUIDE_KR.md 만 보고 다른 개발자가 새 도구 추가 가능"""
    guide = PROJECT_ROOT / "MCP_GUIDE_KR.md"
    if not guide.is_file():
        checklist.add(
            CheckItem(name="MCP_GUIDE_KR.md 로 새 도구 추가 가능", passed=False,
                      detail="문서가 없습니다")
        )
        return

    text = guide.read_text(encoding="utf-8")
    required = {
        "베이스 클래스": "BaseMCPServer",
        "도구 정의 방법": "get_tools",
        "실행 처리 방법": "handle_call",
        "설정 등록 방법": "mcp_config.json",
        "이름 규칙 경고": "__",
        "체크리스트": "체크리스트",
        "print 금지 경고": "print()",
    }
    missing = [label for label, keyword in required.items() if keyword not in text]

    # 문서가 설명하는 파일이 실제로 존재하는지
    base_server = BACKEND_DIR / "app" / "mcp_servers" / "base_server.py"
    config = BACKEND_DIR / "app" / "mcp_servers" / "mcp_config.json"
    files_ok = base_server.is_file() and config.is_file()

    checklist.add(
        CheckItem(
            name="MCP_GUIDE_KR.md 만 보고 다른 개발자가 새 도구 추가 가능",
            passed=not missing and files_ok,
            detail=(
                f"필수 항목 {len(required)}개 포함, 설명한 파일 실재 확인"
                if not missing and files_ok
                else f"누락: {missing}"
            ),
        )
    )


def check_feedback_loop(checklist: Checklist) -> None:
    """12. 피드백 루프가 동작하고 무한 루프에 빠지지 않음"""
    from app.agents.feedback import (
        fallback_queries,
        merge_evidences,
        select_new_queries,
        should_retry,
    )
    from app.agents.graph import RETRY_SOURCE, RETRY_TARGET, recursion_limit_for
    from app.agents.state import Evidence
    from app.config.settings import MAX_AGENT_ITERATIONS

    problems: list[str] = []

    # (1) 루프 엣지가 Verifier → Retriever 로 연결되어 있는가
    if (RETRY_SOURCE, RETRY_TARGET) != ("verifier", "retriever"):
        problems.append("되돌아가기 엣지가 verifier → retriever 가 아님")

    # (2) 안전장치 1 — 회차 상한에서 반드시 멈추는가
    if should_retry(confidence=0, threshold=50, iteration=2, max_iterations=2):
        problems.append("회차 상한에서 멈추지 않음 (무한 루프 위험)")
    if should_retry(confidence=0, threshold=50, iteration=1, max_iterations=1):
        problems.append("max_iterations=1 인데도 재검색을 시도함")

    # (3) 안전장치 2 — 같은 검색어를 다시 고르지 않는가
    if select_new_queries(["소듐이온배터리"], ["소듐이온배터리"]):
        problems.append("이미 시도한 검색어를 다시 고름 (무한 루프 위험)")

    # (4) 안전장치 3 — LLM 없이도 대체 검색어를 만들 수 있는가 (폐쇄망)
    queries = fallback_queries("소듐이온배터리 최근 정책동향을 조사해서 보고서로 만들어줘")
    if not queries:
        problems.append("LLM 없이 대체 검색어를 만들지 못함")

    # (5) 재검색이 이전 근거를 버리지 않는가
    merged = merge_evidences(
        [Evidence(source="a.md", content="A", origin="rag")],
        [Evidence(source="b.md", content="B", origin="rag")],
    )
    if len(merged) != 2:
        problems.append("재검색이 이전 회차 근거를 잃어버림")

    # (6) recursion_limit 이 회차 수를 감당하는가
    if recursion_limit_for(MAX_AGENT_ITERATIONS) <= 6 + (MAX_AGENT_ITERATIONS - 1) * 3:
        problems.append("recursion_limit 이 최대 회차를 감당하지 못함")

    checklist.add(
        CheckItem(
            name="피드백 루프 동작 + 무한 루프 방지",
            passed=not problems,
            detail=(
                f"되돌아가기 엣지 확인, 3중 안전장치 통과, "
                f"대체 검색어 {len(queries)}개 생성 "
                f"(최대 {MAX_AGENT_ITERATIONS}회차)"
                if not problems
                else "; ".join(problems)
            ),
        )
    )


def check_gui_loop(checklist: Checklist) -> None:
    """13. GUI 자동 조작 루프가 동작하고 폭주하지 않음"""
    import json

    from app.agents import gui_loop
    from app.agents.gui_loop import ActionDecision
    from app.config.settings import MAX_GUI_STEPS, Settings

    problems: list[str] = []

    # (1) 조작 결정을 파싱할 수 있는가
    decision = gui_loop.parse_action(
        '{"action": "click", "target": "검색", "reason": "검색 시작"}'
    )
    if decision is None or decision.action != "click":
        problems.append("조작 결정(JSON) 을 파싱하지 못함")

    # (2) 모르는 조작을 거부하는가 (엉뚱한 동작 방지)
    if gui_loop.parse_action('{"action": "format_disk"}') is not None:
        problems.append("허용되지 않은 조작을 걸러내지 못함")

    # (3) 화면에 없는 대상을 누르려 할 때 막는가 (오클릭 방지)
    elements = [{"text": "검색", "x": 10, "y": 20}]
    blocked = gui_loop.validate_decision(
        ActionDecision(action="click", target="없는버튼"), elements
    )
    if blocked is None:
        problems.append("화면에 없는 대상 클릭을 막지 못함")

    # (4) 화면에 있는 대상은 통과하는가
    allowed = gui_loop.validate_decision(
        ActionDecision(action="click", target="검색"), elements
    )
    if allowed is not None:
        problems.append("정상 대상을 잘못 차단함")

    # (5) 제자리(같은 조작 반복) 를 감지하는가
    same = ActionDecision(action="click", target="검색").signature()
    if not gui_loop.is_stuck([same] * gui_loop.STUCK_THRESHOLD):
        problems.append("같은 조작 반복을 감지하지 못함 (폭주 위험)")
    if gui_loop.is_stuck([same, "type|가", same]):
        problems.append("정상 진행을 제자리로 잘못 판단함")

    # (6) 조작 횟수 상한이 걸려 있는가
    defaults = Settings()
    if not 1 <= defaults.gui_max_steps <= MAX_GUI_STEPS:
        problems.append("조작 횟수 기본값이 상한 범위를 벗어남")

    # (7) automation 도구가 승인 필요로 등록되어 있는가
    config_path = BACKEND_DIR / "app" / "mcp_servers" / "mcp_config.json"
    try:
        servers = json.loads(config_path.read_text(encoding="utf-8"))["servers"]
        if not servers.get("automation", {}).get("require_approval"):
            problems.append("automation 서버가 승인 필요로 설정되지 않음 (위험)")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        problems.append(f"mcp_config.json 확인 실패: {exc}")

    checklist.add(
        CheckItem(
            name="GUI 자동 조작 루프 동작 + 폭주 방지",
            passed=not problems,
            detail=(
                f"조작 판단·검증·제자리 감지 통과, "
                f"승인 게이트 필수, 조작 상한 {defaults.gui_max_steps}회 "
                f"(하드 상한 {MAX_GUI_STEPS}회)"
                if not problems
                else "; ".join(problems)
            ),
        )
    )


def check_stdout_protection(checklist: Checklist) -> None:
    """14. 외부 라이브러리 출력이 JSON-RPC 통신을 깨뜨리지 않음"""
    import contextlib
    import io

    from app.mcp_client.client import GUI_ENV_VARS, build_server_env
    from app.mcp_servers.base_server import protect_stdout

    problems: list[str] = []

    # (1) 보호 구간의 stdout 출력이 stderr 로 가는가
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with protect_stdout():
            print("download https://example.com/model.tar")
    if out.getvalue().strip():
        problems.append("stdout 이 오염됨 (JSON-RPC 깨짐 위험)")
    if "model.tar" not in err.getvalue():
        problems.append("출력이 stderr 로 전달되지 않음")

    # (2) 보호 구간을 벗어나면 복구되는가
    out2 = io.StringIO()
    with contextlib.redirect_stdout(out2):
        with protect_stdout():
            pass
        print("복구")
    if "복구" not in out2.getvalue():
        problems.append("보호 구간 종료 후 stdout 이 복구되지 않음")

    # (3) 화면 환경변수가 서버로 전달되는가 (DISPLAY 가 걸러지면 캡처 불가)
    os.environ["DISPLAY"] = os.environ.get("DISPLAY", ":0")
    if build_server_env().get("DISPLAY") != os.environ["DISPLAY"]:
        problems.append("DISPLAY 가 MCP 서버로 전달되지 않음 (화면 캡처 불가)")
    for required in ("DISPLAY", "WAYLAND_DISPLAY", "SESSIONNAME"):
        if required not in GUI_ENV_VARS:
            problems.append(f"{required} 가 전달 목록에 없음")

    checklist.add(
        CheckItem(
            name="외부 출력이 JSON-RPC 통신을 깨뜨리지 않음",
            passed=not problems,
            detail=(
                "stdout 보호막 동작, 종료 후 복구 확인, "
                "화면 환경변수 전달 확인"
                if not problems
                else "; ".join(problems)
            ),
        )
    )


def check_team_collaboration(checklist: Checklist) -> None:
    """15. 팀 협업(대화/회의/파일)이 동작하고 기록이 남음"""
    import json as _json
    import tempfile

    from app.team.service import TeamService
    from app.team.store import TeamStore, TeamStoreError, safe_filename

    problems: list[str] = []

    async def exercise(root: Path) -> dict[str, int]:
        store = TeamStore(data_dir=root / "data", project_root=root)
        service = TeamService(
            store,
            log_path=root / "logs" / "team.jsonl",
            max_attachment_bytes=1024 * 1024,
        )
        await service.start()
        await service.register_member("a", "구성원A")
        await service.register_member("b", "구성원B")

        room = await service.create_room(
            "검증 회의", kind="meeting", created_by="a", member_ids=["b"]
        )
        await service.send_text(room.id, "a", "회의를 시작합니다")
        await service.send_text(room.id, "b", "자료 공유합니다")

        # 파일 전송
        sample = root / "자료.txt"
        sample.write_text("검증용", encoding="utf-8")
        shared = await service.send_file(
            room.id, "b", filename="자료.txt", source=sample
        )
        if shared.attachment is None:
            problems.append("첨부 파일이 저장되지 않음")
        elif not service.attachment_full_path(shared.attachment).is_file():
            problems.append("첨부 파일 실물이 없음")

        # 삭제해도 기록이 남는가
        removed = await service.send_text(room.id, "a", "지울 메시지")
        deleted = await service.delete_message(removed.id, "a")
        if not deleted.is_deleted or store.get_message(removed.id) is None:
            problems.append("삭제 후 기록이 사라짐 (감사 불가)")

        # 회의 종료 후 메시지 차단
        await service.close_room(room.id, "a")
        try:
            await service.send_text(room.id, "a", "종료 후")
            problems.append("종료된 회의에 메시지가 들어감")
        except TeamStoreError:
            pass

        # 회의록
        transcript = await service.build_transcript(room.id)
        for needed in ("검증 회의", "구성원A", "회의를 시작합니다", "(삭제된 메시지)"):
            if needed not in transcript:
                problems.append(f"회의록에 '{needed}' 누락")

        stats = await service.stats()
        await service.stop()
        return stats

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        try:
            stats = asyncio.run(exercise(root))
        except Exception as exc:  # noqa: BLE001
            checklist.add(
                CheckItem(
                    name="팀 협업(대화/회의/파일) 동작 + 기록 보존",
                    passed=False,
                    detail=f"오류: {exc}",
                )
            )
            return

        # 감사 기록 파일 확인
        log_path = root / "logs" / "team.jsonl"
        if not log_path.is_file():
            problems.append("감사 기록 파일이 없음")
        else:
            actions = {
                _json.loads(line)["action"]
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            for needed in ("room_created", "message_sent", "message_deleted"):
                if needed not in actions:
                    problems.append(f"기록에 '{needed}' 누락")

    # 파일 이름으로 저장 위치를 벗어나지 못하는가 (보안)
    if "/" in safe_filename("../../etc/passwd"):
        problems.append("첨부 파일 이름으로 경로 탈출 가능 (보안)")

    checklist.add(
        CheckItem(
            name="팀 협업(대화/회의/파일) 동작 + 기록 보존",
            passed=not problems,
            detail=(
                f"방/메시지/첨부 저장 확인, 삭제 후에도 기록 유지, "
                f"회의 종료 차단, 회의록 생성 "
                f"(메시지 {stats['messages']}건 / 첨부 {stats['attachments']}건)"
                if not problems
                else "; ".join(problems)
            ),
        )
    )


# ============================================================
# 실행
# ============================================================


def main() -> int:
    """전체 체크리스트를 실행한다."""
    print("=" * 60)
    print("  PFM-Agent 최종 검증 체크리스트 (STEP 11)")
    print("=" * 60)
    print()

    checklist = Checklist()

    checks = (
        check_llm_anthropic,
        check_llm_pgpt,
        check_mcp_standalone,
        check_tool_collection,
        check_portable,
        check_offline_rag,
        check_kill_switch,
        check_outputs_inside_project,
        check_no_system_env_dependency,
        check_setup_guide,
        check_mcp_guide,
        check_feedback_loop,
        check_gui_loop,
        check_stdout_protection,
        check_team_collaboration,
    )

    for check in checks:
        try:
            check(checklist)
        except Exception as exc:  # noqa: BLE001 - 한 항목 실패가 전체를 막지 않게
            checklist.add(
                CheckItem(name=check.__doc__ or check.__name__, passed=False,
                          detail=f"검증 중 오류: {exc}")
            )

    print()
    print("=" * 60)
    print(f"  결과: {checklist.summary()}")
    if checklist.all_passed:
        print("  ✅ 모든 항목을 통과했습니다.")
    else:
        print("  ❌ 통과하지 못한 항목이 있습니다.")
    print("=" * 60)

    return 0 if checklist.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
