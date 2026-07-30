"""
실제 화면 환경 검증 스크립트.

**화면이 있는 PC 에서만** 확인할 수 있는 것들을 실제로 실행해 본다.
개발 컨테이너(화면 없음)에서는 확인이 불가능한 항목들이므로,
회사 PC 에 설치한 뒤 **한 번 실행해 결과를 확인**하는 용도다.

실행:
    cd backend
    uv run python ../scripts/verify_display.py

    # 마우스를 실제로 움직여 확인까지 하려면 (선택)
    uv run python ../scripts/verify_display.py --allow-input

검증 항목
---------
  1. 화면 캡처 라이브러리 사용 가능 여부
  2. 실제 화면 캡처 (크기 / 저장 위치가 프로젝트 내부인지)
  3. MCP screen 서버를 통한 capture_screen
  4. OCR 라이브러리 + 모델이 **프로젝트 내부**에 있는지
  5. 실제 화면에서 글자 읽기 (list_ui_elements)
  6. 자연어로 UI 요소 찾기 (find_ui_element)
  7. 마우스/키보드 조작 라이브러리 사용 가능 여부
  8. (--allow-input) 마우스를 실제로 움직여 좌표가 반영되는지

⚠️ 기본 동작은 **읽기 전용**이다.
   마우스/키보드를 실제로 움직이는 것은 `--allow-input` 을 줄 때만 한다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

# 프로젝트 경로 설정 (절대경로 하드코딩 금지)
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]
BACKEND_DIR: Path = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

#: 마우스를 움직여 볼 목표 좌표 (화면 좌상단 근처 — 안전한 빈 영역)
_PROBE_POINT: tuple[int, int] = (10, 10)


@dataclass
class Item:
    """검증 항목 하나."""

    name: str
    ok: bool
    detail: str = ""
    skipped: bool = False

    @property
    def mark(self) -> str:
        """결과 표시."""
        if self.skipped:
            return "건너뜀"
        return "가능" if self.ok else "불가"


class Report:
    """검증 결과 모음."""

    def __init__(self) -> None:
        self.items: list[Item] = []

    def add(self, item: Item) -> Item:
        """항목을 추가하고 즉시 출력한다."""
        self.items.append(item)
        print(f"  [{item.mark}] {item.name}")
        if item.detail:
            for line in item.detail.splitlines():
                print(f"          {line}")
        return item

    def summary(self) -> str:
        """요약 문자열."""
        ok = sum(1 for item in self.items if item.ok and not item.skipped)
        skipped = sum(1 for item in self.items if item.skipped)
        failed = len(self.items) - ok - skipped
        return f"가능 {ok} / 불가 {failed} / 건너뜀 {skipped}"


# ============================================================
# 개별 검증
# ============================================================


def check_capture_library(report: Report) -> bool:
    """화면 캡처 라이브러리를 쓸 수 있는지 확인한다."""
    available: list[str] = []
    for module in ("mss", "PIL"):
        try:
            __import__(module)
            available.append(module)
        except ImportError:
            pass

    ok = "PIL" in available
    report.add(
        Item(
            name="화면 캡처 라이브러리",
            ok=ok,
            detail=(
                f"사용 가능: {', '.join(available)}"
                if ok
                else "PIL 이 없습니다. first_time_setup.bat 를 다시 실행하세요."
            ),
        )
    )
    return ok


def check_real_capture(report: Report) -> Path | None:
    """실제 화면을 캡처해 본다."""
    from app.mcp_servers.screen_server import SCREENSHOT_DIR, grab_screen

    try:
        image = grab_screen(None)
    except Exception as exc:  # noqa: BLE001 - 사유를 그대로 보여준다
        report.add(
            Item(
                name="실제 화면 캡처",
                ok=False,
                detail=f"{exc}".splitlines()[0],
            )
        )
        return None

    inside = SCREENSHOT_DIR.resolve().is_relative_to(PROJECT_ROOT)
    report.add(
        Item(
            name="실제 화면 캡처",
            ok=True,
            detail=(
                f"크기 {image.width}x{image.height}\n"
                f"저장 폴더: {SCREENSHOT_DIR.relative_to(PROJECT_ROOT)} "
                f"({'프로젝트 내부 OK' if inside else '⚠️ 프로젝트 밖!'})"
            ),
        )
    )
    return SCREENSHOT_DIR


async def check_mcp_capture(report: Report) -> None:
    """MCP screen 서버를 통해 캡처가 되는지 확인한다."""
    from app.mcp_client.client import MCPClient

    try:
        client = MCPClient.from_config(timeout=40)
        async with client:
            result = await client.call_tool("screen", "capture_screen", {})
    except Exception as exc:  # noqa: BLE001
        report.add(Item(name="MCP 서버를 통한 화면 캡처", ok=False, detail=str(exc)))
        return

    if result.is_error:
        report.add(
            Item(
                name="MCP 서버를 통한 화면 캡처",
                ok=False,
                detail=result.text.splitlines()[0],
            )
        )
        return

    structured = result.structured or {}
    report.add(
        Item(
            name="MCP 서버를 통한 화면 캡처",
            ok=True,
            detail=(
                f"{structured.get('message', result.text)}\n"
                f"파일: {structured.get('path', '?')}"
            ),
        )
    )


def check_ocr_models(report: Report) -> bool:
    """OCR 라이브러리와 모델 위치를 확인한다."""
    from app.mcp_servers.screen_server import ocr_model_dirs

    # 1) 라이브러리
    missing: list[str] = []
    for module in ("paddleocr", "paddle", "numpy"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)

    if missing:
        report.add(
            Item(
                name="OCR 라이브러리",
                ok=False,
                detail=(
                    f"없는 패키지: {', '.join(missing)}\n"
                    f"해결: uv sync --extra vision"
                ),
            )
        )
        return False

    report.add(Item(name="OCR 라이브러리", ok=True, detail="paddleocr + paddle 준비됨"))

    # 2) 모델 위치 (프로젝트 내부여야 폐쇄망/USB 에서 동작한다)
    problems: list[str] = []
    found: list[str] = []
    for key, raw in ocr_model_dirs().items():
        path = Path(raw)
        if not path.resolve().is_relative_to(PROJECT_ROOT):
            problems.append(f"{key} 가 프로젝트 밖: {path}")
            continue
        label = str(path.relative_to(PROJECT_ROOT))
        if any(path.rglob("*.pdmodel")) or any(path.rglob("*.pdiparams")):
            found.append(f"{label} (모델 있음)")
        else:
            found.append(f"{label} (비어 있음)")

    has_models = all("모델 있음" in item for item in found)
    report.add(
        Item(
            name="OCR 모델이 프로젝트 내부에 있는지",
            ok=not problems and has_models,
            detail=(
                "\n".join(problems)
                if problems
                else "\n".join(found)
                + (
                    ""
                    if has_models
                    else "\n인터넷 되는 PC 에서 "
                    "`python scripts/download_models.py` 를 실행한 뒤\n"
                    "models 폴더째 USB 로 옮기세요."
                )
            ),
        )
    )
    return not problems and has_models


async def check_ocr_reading(report: Report, ocr_ready: bool) -> None:
    """실제 화면에서 글자를 읽어 본다."""
    if not ocr_ready:
        report.add(
            Item(
                name="실제 화면에서 글자 읽기",
                ok=False,
                skipped=True,
                detail="OCR 모델이 준비되지 않아 건너뜁니다.",
            )
        )
        return

    from app.mcp_client.client import MCPClient

    try:
        client = MCPClient.from_config(timeout=60)
        async with client:
            result = await client.call_tool("screen", "list_ui_elements", {"limit": 20})
    except Exception as exc:  # noqa: BLE001
        report.add(Item(name="실제 화면에서 글자 읽기", ok=False, detail=str(exc)))
        return

    if result.is_error:
        report.add(
            Item(
                name="실제 화면에서 글자 읽기",
                ok=False,
                detail=result.text.splitlines()[0],
            )
        )
        return

    structured = result.structured or {}
    elements = structured.get("elements", [])
    preview = "\n".join(
        f"- \"{item.get('text')}\" ({item.get('x')}, {item.get('y')})"
        for item in elements[:5]
    )
    report.add(
        Item(
            name="실제 화면에서 글자 읽기",
            ok=bool(elements),
            detail=(
                f"인식한 요소 {structured.get('total', len(elements))}개\n{preview}"
                if elements
                else "글자를 하나도 읽지 못했습니다. 창이 열려 있는지 확인하세요."
            ),
        )
    )

    # 읽은 글자 중 하나로 find_ui_element 를 시험한다.
    if not elements:
        return

    target = str(elements[0].get("text", "")).strip()
    try:
        client = MCPClient.from_config(timeout=60)
        async with client:
            found = await client.call_tool(
                "screen", "find_ui_element", {"description": target}
            )
    except Exception as exc:  # noqa: BLE001
        report.add(Item(name="자연어로 UI 요소 찾기", ok=False, detail=str(exc)))
        return

    structured = found.structured or {}
    report.add(
        Item(
            name="자연어로 UI 요소 찾기",
            ok=not found.is_error,
            detail=(
                f"'{target}' → 좌표 ({structured.get('x')}, {structured.get('y')}) "
                f"일치도 {structured.get('match_score')}"
                if not found.is_error
                else found.text.splitlines()[0]
            ),
        )
    )


def check_input_library(report: Report) -> bool:
    """마우스/키보드 조작 라이브러리를 쓸 수 있는지 확인한다."""
    try:
        import pyautogui
    # ⚠️ BaseException 을 잡는 이유: pyautogui 는 리눅스에서 tkinter 가 없으면
    #    ImportError 가 아니라 **sys.exit()** 로 죽는다. (SystemExit)
    #    Exception 만 잡으면 이 검증 스크립트 자체가 중단된다.
    except BaseException as exc:  # noqa: BLE001
        report.add(
            Item(
                name="마우스/키보드 조작 라이브러리",
                ok=False,
                detail=(
                    f"pyautogui 를 쓸 수 없습니다: {type(exc).__name__}: {exc}\n"
                    f"Windows 에서는 보통 정상입니다. "
                    f"리눅스라면 python3-tk 가 필요합니다."
                ),
            )
        )
        return False

    try:
        size = pyautogui.size()
        position = pyautogui.position()
    except Exception as exc:  # noqa: BLE001
        report.add(
            Item(
                name="마우스/키보드 조작 라이브러리",
                ok=False,
                detail=f"화면 정보를 읽지 못했습니다: {exc}",
            )
        )
        return False

    report.add(
        Item(
            name="마우스/키보드 조작 라이브러리",
            ok=True,
            detail=(
                f"pyautogui 준비됨 — 화면 {size.width}x{size.height}, "
                f"현재 마우스 ({position.x}, {position.y})\n"
                f"FAILSAFE: {pyautogui.FAILSAFE} (마우스를 좌상단으로 밀면 즉시 중단)"
            ),
        )
    )
    return True


def check_real_input(report: Report, input_ready: bool, allow: bool) -> None:
    """마우스를 실제로 움직여 좌표가 반영되는지 확인한다."""
    if not allow:
        report.add(
            Item(
                name="마우스 실제 이동 확인",
                ok=False,
                skipped=True,
                detail="--allow-input 을 주면 실제로 마우스를 움직여 확인합니다.",
            )
        )
        return

    if not input_ready:
        report.add(
            Item(
                name="마우스 실제 이동 확인",
                ok=False,
                skipped=True,
                detail="조작 라이브러리를 쓸 수 없어 건너뜁니다.",
            )
        )
        return

    import pyautogui

    origin = pyautogui.position()
    try:
        pyautogui.moveTo(*_PROBE_POINT, duration=0)
        moved = pyautogui.position()
    finally:
        # 원래 위치로 되돌린다. (사용자 화면을 건드린 흔적을 남기지 않는다)
        pyautogui.moveTo(origin.x, origin.y, duration=0)

    ok = abs(moved.x - _PROBE_POINT[0]) <= 2 and abs(moved.y - _PROBE_POINT[1]) <= 2
    report.add(
        Item(
            name="마우스 실제 이동 확인",
            ok=ok,
            detail=(
                f"{_PROBE_POINT} 로 이동 요청 → 실제 ({moved.x}, {moved.y}) "
                f"→ 원위치 복귀"
            ),
        )
    )


# ============================================================
# 실행
# ============================================================


async def run(allow_input: bool) -> int:
    """전체 검증을 실행한다."""
    print("=" * 60)
    print("  PFM-Agent 실제 화면 환경 검증")
    print("  (화면이 있는 PC 에서만 의미 있는 항목들입니다)")
    print("=" * 60)
    print()

    report = Report()

    check_capture_library(report)
    check_real_capture(report)
    await check_mcp_capture(report)
    print()

    ocr_ready = check_ocr_models(report)
    await check_ocr_reading(report, ocr_ready)
    print()

    input_ready = check_input_library(report)
    check_real_input(report, input_ready, allow_input)

    print()
    print("=" * 60)
    print(f"  결과: {report.summary()}")

    blocked = [item for item in report.items if not item.ok and not item.skipped]
    if blocked:
        print()
        print("  ⚠️  아래 기능은 이 PC 에서 사용할 수 없습니다.")
        for item in blocked:
            print(f"      - {item.name}")
        print()
        print("  앱은 멈추지 않습니다. 해당 기능만 건너뛰고 동작합니다.")
    else:
        print("  ✅ 화면 관련 기능을 모두 사용할 수 있습니다.")
    print("=" * 60)
    return 0


def main() -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        description="PFM-Agent 실제 화면 환경 검증 (화면 있는 PC 에서 실행)"
    )
    parser.add_argument(
        "--allow-input",
        action="store_true",
        help="마우스를 실제로 움직여 확인합니다. (확인 후 원위치로 복귀)",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.allow_input))


if __name__ == "__main__":
    raise SystemExit(main())
