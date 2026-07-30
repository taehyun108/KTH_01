"""
실행 전 점검 (Preflight Check).

`run_all.bat` 이 호출한다. 앱을 켜기 전에 문제를 미리 찾아
**비개발자도 알아볼 수 있는 한글 안내**로 알려준다.

점검 항목
---------
  1. `.env` 파일 존재 및 LLM 설정
  2. 가상환경(.venv) 및 주요 라이브러리
  3. 런타임 폴더 (data / logs / output) 쓰기 가능 여부
  4. 백엔드 포트 사용 가능 여부
  5. MCP 서버 정상 기동 (실제로 띄워서 확인)
  6. 로컬 모델 준비 상태 (없어도 경고만)

종료 코드
---------
  0 : 실행 가능 (경고가 있어도 진행 가능)
  1 : 실행 불가 (반드시 해결해야 함)
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

# 프로젝트 루트 = 이 파일(scripts/preflight_check.py) 의 부모의 부모
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"

# backend 를 import 경로에 추가한다. (설정/MCP 모듈 재사용)
sys.path.insert(0, str(BACKEND_DIR))


class CheckResult:
    """점검 결과 모음."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str, fix: str = "") -> None:
        """반드시 해결해야 하는 문제."""
        self.errors.append(f"{message}\n      해결: {fix}" if fix else message)

    def warn(self, message: str) -> None:
        """알아두면 좋은 사항. (실행은 가능)"""
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        """실행 가능한지 여부."""
        return not self.errors


def check_env_file(result: CheckResult) -> None:
    """`.env` 파일과 LLM 설정을 확인한다."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        result.error(
            ".env 설정 파일이 없습니다.",
            "first_time_setup.bat 를 먼저 실행하세요.",
        )
        return

    try:
        from app.config.settings import load_settings
    except ImportError as exc:
        result.error(
            f"설정을 읽을 수 없습니다: {exc}",
            "first_time_setup.bat 를 다시 실행하세요.",
        )
        return

    settings = load_settings()
    provider = settings.llm_provider

    if provider == "pgpt":
        if not settings.pgpt_base_url or "your-internal" in settings.pgpt_base_url:
            result.error(
                "사내 P-GPT 주소(PGPT_BASE_URL)가 설정되지 않았습니다.",
                ".env 파일을 메모장으로 열어 회사에서 받은 주소를 입력하세요.",
            )
        if not settings.pgpt_api_key:
            result.error(
                "사내 P-GPT 키(PGPT_API_KEY)가 비어 있습니다.",
                ".env 파일에 회사에서 받은 키를 입력하세요.",
            )
    elif provider == "anthropic" and not settings.anthropic_api_key:
        result.warn(
            "ANTHROPIC_API_KEY 가 비어 있습니다. "
            "AI 응답 없이 기본 동작만 수행합니다."
        )
    elif provider == "openai" and not settings.openai_api_key:
        result.warn(
            "OPENAI_API_KEY 가 비어 있습니다. AI 응답 없이 기본 동작만 수행합니다."
        )

    print(f"  [확인] LLM 제공자: {provider}")


def check_venv(result: CheckResult) -> None:
    """가상환경과 주요 라이브러리를 확인한다."""
    venv_dir = BACKEND_DIR / ".venv"
    if not venv_dir.is_dir():
        result.error(
            "가상환경(.venv)이 없습니다.",
            "first_time_setup.bat 를 먼저 실행하세요.",
        )
        return

    missing: list[str] = []
    for module, label in (
        ("fastapi", "웹 서버"),
        ("mcp", "도구 서버"),
        ("docx", "Word 생성"),
        ("pptx", "PPT 생성"),
    ):
        try:
            __import__(module)
        except ImportError:
            missing.append(f"{label}({module})")

    if missing:
        result.error(
            f"필수 라이브러리가 없습니다: {', '.join(missing)}",
            "first_time_setup.bat 를 다시 실행하세요.",
        )
    else:
        print("  [확인] 필수 라이브러리 설치됨")

    _check_venv_relocated(result, venv_dir)


def _check_venv_relocated(result: CheckResult, venv_dir: Path) -> None:
    """
    폴더를 옮긴 뒤 가상환경이 깨졌는지 확인한다.

    ⚠️ 왜 필요한가
    --------------
    `.venv` 안의 실행 파일(`uvicorn.exe`, `pytest.exe` 등)에는 **만들어질 때의
    절대경로가 새겨진다.** 그래서 폴더를 다른 위치로 옮기거나 이름을 바꾸면
    그 실행 파일들이 동작하지 않는다. (`uv sync` 로도 복구되지 않는다)

    PFM-Agent 는 이 문제를 피하려고 실행 스크립트에서 `python -m ...` 형태로만
    실행하므로 앱 동작에는 문제가 없다. 다만 사용자가 `uv run uvicorn` 처럼
    직접 실행하면 실패하므로, 상태를 알려 주고 복구 방법을 안내한다.
    """
    # 인터프리터 위치가 현재 폴더 안을 가리키는지 확인한다.
    interpreter = Path(sys.prefix).resolve()
    if interpreter == venv_dir.resolve():
        print("  [확인] 가상환경 위치 정상 (폴더 이동 흔적 없음)")
        return

    result.warn(
        "가상환경이 다른 위치를 가리킵니다. (폴더를 옮겼거나 이름을 바꿨을 때 생김)\n"
        "      앱 실행에는 문제가 없습니다. "
        "'uv run uvicorn' 같은 직접 실행이 실패하면\n"
        "      backend\\.venv 폴더를 지우고 first_time_setup.bat 를 다시 실행하세요."
    )


def check_directories(result: CheckResult) -> None:
    """런타임 폴더에 쓸 수 있는지 확인한다."""
    for name in ("data", "logs", "output"):
        directory = PROJECT_ROOT / name
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            result.error(
                f"'{name}' 폴더에 파일을 저장할 수 없습니다: {exc}",
                "USB 가 쓰기 금지 상태인지, 폴더 권한이 있는지 확인하세요.",
            )
            return

    print("  [확인] 저장 폴더 (data / logs / output) 쓰기 가능")


def check_port(result: CheckResult) -> None:
    """백엔드 포트가 비어 있는지 확인한다."""
    try:
        from app.config.settings import load_settings

        port = load_settings().backend_port
    except Exception:  # noqa: BLE001
        port = 8756

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            result.warn(
                f"{port} 번 포트를 이미 사용 중입니다. "
                f"PFM-Agent 가 이미 실행 중일 수 있습니다."
            )
        else:
            print(f"  [확인] 백엔드 포트 {port} 사용 가능")


async def check_mcp_servers(result: CheckResult) -> None:
    """MCP 서버를 실제로 띄워 정상 동작하는지 확인한다."""
    try:
        from app.mcp_client.client import MCPClient
    except ImportError as exc:
        result.error(f"도구 서버를 불러올 수 없습니다: {exc}")
        return

    try:
        client = MCPClient.from_config(timeout=30)
        async with client:
            connected = len(client.connected_servers)
            tools = client.total_tool_count()
            failed = client.failed_servers
    except Exception as exc:  # noqa: BLE001
        result.error(
            f"도구 서버를 시작하지 못했습니다: {exc}",
            "first_time_setup.bat 를 다시 실행하세요.",
        )
        return

    if failed:
        for name, reason in failed.items():
            result.warn(f"'{name}' 도구 서버가 시작되지 않았습니다: {reason}")

    if connected == 0:
        result.error(
            "도구 서버가 하나도 시작되지 않았습니다.",
            "first_time_setup.bat 를 다시 실행하세요.",
        )
    else:
        print(f"  [확인] 도구 서버 {connected}개 / 도구 {tools}개 정상")


def check_models(result: CheckResult) -> None:
    """로컬 모델 준비 상태를 확인한다. (없어도 경고만)"""
    suffixes = (".bin", ".safetensors", ".onnx", ".pdmodel", ".pdiparams")

    def has_model(directory: Path) -> bool:
        return directory.is_dir() and any(
            path.suffix in suffixes for path in directory.rglob("*") if path.is_file()
        )

    if has_model(PROJECT_ROOT / "models" / "bge-m3"):
        print("  [확인] 문서 검색 모델 준비됨")
    else:
        result.warn(
            "문서 검색 모델(BGE-M3)이 없습니다. "
            "키워드 검색으로 동작하며 정확도가 낮을 수 있습니다."
        )

    if not has_model(PROJECT_ROOT / "models" / "ocr"):
        result.warn(
            "글자 인식(OCR) 모델이 없습니다. 화면 인식 기능을 쓸 수 없습니다."
        )


async def run_checks() -> int:
    """모든 점검을 수행하고 결과를 출력한다."""
    print("=" * 56)
    print("  PFM-Agent 실행 전 점검")
    print("=" * 56)

    result = CheckResult()

    check_env_file(result)
    check_venv(result)
    check_directories(result)
    check_port(result)
    await check_mcp_servers(result)
    check_models(result)

    print("-" * 56)

    if result.warnings:
        print("  ⚠️  참고 사항")
        for warning in result.warnings:
            print(f"      - {warning}")
        print()

    if result.errors:
        print("  ❌ 실행할 수 없습니다. 아래 문제를 해결하세요.")
        for error in result.errors:
            print(f"      - {error}")
        print("=" * 56)
        return 1

    print("  ✅ 점검 완료. 실행할 수 있습니다.")
    print("=" * 56)
    return 0


def main() -> int:
    """진입점."""
    try:
        return asyncio.run(run_checks())
    except KeyboardInterrupt:  # pragma: no cover
        return 1


if __name__ == "__main__":
    sys.exit(main())
