"""
automation MCP 서버 — PC 자동화 도구. (STEP 6 구현)

제공 도구:
  - click(x, y, button) : 마우스 클릭
  - type_text(text)     : 텍스트 입력
  - key_press(key)      : 키 입력 (조합키 지원)
  - open_browser(url)   : 브라우저 열기 (화이트리스트 검사)

🔴 안전 설계
------------
1. **승인 게이트 필수**
   `mcp_config.json` 에 `require_approval: true` 로 등록되어 있어
   ToolRegistry 가 사용자 승인 없이는 호출 자체를 막는다.

2. **좌표 범위 검사**
   화면 밖 좌표는 거부한다. (엉뚱한 모니터/영역 클릭 방지)

3. **화이트리스트**
   `open_browser` 는 허용된 도메인만 열 수 있다.

4. **PyAutoGUI FAILSAFE**
   마우스를 화면 좌상단 모서리로 옮기면 자동화가 즉시 중단된다. (라이브러리 기본 안전장치)

5. **위험 키 조합 차단**
   Alt+F4, Ctrl+Alt+Del 등 시스템을 종료/방해하는 조합은 거부한다.

단독 실행:
    python -m app.mcp_servers.automation_server
"""

from __future__ import annotations

import webbrowser
from typing import Any

from mcp.types import Tool

from app.mcp_servers.base_server import BaseMCPServer, MCPToolError
from app.security.whitelist import check_url

#: 허용하는 마우스 버튼
VALID_BUTTONS: frozenset[str] = frozenset({"left", "right", "middle"})

#: 한 번에 입력할 수 있는 최대 글자 수 (오작동으로 인한 대량 입력 방지)
MAX_TEXT_LENGTH: int = 5000

#: 키 이름 표준화 (사용자/LLM 이 다양하게 표현할 수 있음)
KEY_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "escape": "esc",
    "return": "enter",
    "del": "delete",
    "windows": "win",
    "cmd": "command",
    "스페이스": "space",
    "엔터": "enter",
    "탭": "tab",
}


def _normalize_key(part: str) -> str:
    """키 이름 하나를 표준 이름으로 바꾼다."""
    cleaned = part.strip().lower()
    return KEY_ALIASES.get(cleaned, cleaned)


#: 차단하는 위험 키 조합 (시스템 종료/작업 방해)
#: ⚠️ 반드시 `_normalize_key` 를 거쳐 만든다.
#:    별칭 정규화 후의 이름과 어긋나면 차단이 무력화되기 때문이다.
#:    (예: 'escape' 로 적어두면 'esc' 로 정규화된 입력을 놓친다)
_BLOCKED_COMBO_SOURCE: tuple[tuple[str, ...], ...] = (
    ("alt", "f4"),  # 창 강제 종료
    ("ctrl", "alt", "delete"),  # 시스템 메뉴
    ("ctrl", "shift", "escape"),  # 작업 관리자
    ("win", "l"),  # 화면 잠금
    ("win", "r"),  # 실행 창
)

BLOCKED_KEY_COMBOS: frozenset[frozenset[str]] = frozenset(
    frozenset(_normalize_key(part) for part in combo)
    for combo in _BLOCKED_COMBO_SOURCE
)


# ============================================================
# 순수 로직 (환경에 의존하지 않아 단독 테스트 가능)
# ============================================================


def parse_key_combo(key: str) -> list[str]:
    """
    키 문자열을 개별 키 목록으로 분해한다.

    'ctrl+c' → ['ctrl', 'c'] / 'Enter' → ['enter']

    Raises:
        MCPToolError: 비어 있거나 형식이 잘못된 경우
    """
    if not key or not key.strip():
        raise MCPToolError("입력할 키를 지정하세요. (예: enter, ctrl+c)")

    parts = [part.strip().lower() for part in key.split("+") if part.strip()]
    if not parts:
        raise MCPToolError(f"키 형식을 해석할 수 없습니다: {key}")

    return [_normalize_key(part) for part in parts]


def ensure_key_allowed(keys: list[str]) -> None:
    """
    위험한 키 조합인지 확인한다.

    Raises:
        MCPToolError: 차단 대상인 경우
    """
    combo = frozenset(keys)
    if combo in BLOCKED_KEY_COMBOS:
        raise MCPToolError(
            f"'{'+'.join(keys)}' 은(는) 시스템에 영향을 줄 수 있어 사용할 수 없습니다.\n"
            f"이 작업이 꼭 필요하면 사용자가 직접 수행해 주세요."
        )


def validate_click(
    x: int, y: int, button: str, screen_size: tuple[int, int] | None
) -> tuple[int, int, str]:
    """
    클릭 좌표와 버튼을 검증한다.

    Args:
        screen_size: (너비, 높이). None 이면 범위 검사를 건너뛴다.

    Raises:
        MCPToolError: 값이 잘못된 경우
    """
    button_clean = (button or "left").strip().lower()
    if button_clean not in VALID_BUTTONS:
        raise MCPToolError(
            f"'{button}' 은(는) 사용할 수 없는 마우스 버튼입니다. "
            f"({', '.join(sorted(VALID_BUTTONS))} 중 하나여야 합니다)"
        )

    if x < 0 or y < 0:
        raise MCPToolError(f"좌표는 0 이상이어야 합니다. (받은 값: {x}, {y})")

    if screen_size is not None:
        width, height = screen_size
        if x >= width or y >= height:
            raise MCPToolError(
                f"({x}, {y}) 는 화면 범위를 벗어납니다. "
                f"현재 화면 크기는 {width}x{height} 입니다.\n"
                f"screen.find_ui_element 로 올바른 좌표를 먼저 확인하세요."
            )

    return x, y, button_clean


def validate_text(text: str) -> str:
    """
    입력할 텍스트를 검증한다.

    Raises:
        MCPToolError: 너무 길거나 비어 있는 경우
    """
    if text is None or text == "":
        raise MCPToolError("입력할 텍스트가 비어 있습니다.")
    if len(text) > MAX_TEXT_LENGTH:
        raise MCPToolError(
            f"입력할 텍스트가 너무 깁니다 ({len(text):,}자). "
            f"{MAX_TEXT_LENGTH:,}자 이하로 나누어 입력하세요."
        )
    return text


# ============================================================
# 환경 의존 기능 (지연 import)
# ============================================================


def _load_pyautogui() -> Any:
    """
    PyAutoGUI 를 지연 로드한다.

    Raises:
        MCPToolError: 설치되지 않았거나 화면이 없는 환경인 경우
    """
    try:
        import pyautogui
    except ImportError as exc:
        raise MCPToolError(
            "PC 자동화 라이브러리(PyAutoGUI)가 설치되어 있지 않습니다.\n"
            "  해결: first_time_setup.bat 를 다시 실행하세요."
        ) from exc
    except Exception as exc:
        raise MCPToolError(
            "화면이 없는 환경에서는 PC 조작을 할 수 없습니다.\n"
            "  (원격 접속이나 서버 환경에서는 마우스/키보드 조작이 불가능합니다)\n"
            f"  (상세: {exc})"
        ) from exc

    # 화면 좌상단으로 마우스를 옮기면 자동화가 즉시 중단된다. (비상 탈출)
    pyautogui.FAILSAFE = True
    # 각 동작 사이에 짧은 간격을 둬 화면이 따라올 시간을 준다.
    pyautogui.PAUSE = 0.1
    return pyautogui


def get_screen_size() -> tuple[int, int] | None:
    """
    화면 크기를 구한다. 알 수 없으면 None. (범위 검사를 건너뛴다)
    """
    try:
        pyautogui = _load_pyautogui()
        size = pyautogui.size()
        return int(size[0]), int(size[1])
    except MCPToolError:
        return None
    except Exception:  # noqa: BLE001
        return None


# ============================================================
# MCP 서버
# ============================================================


class AutomationMCPServer(BaseMCPServer):
    """마우스/키보드/브라우저 조작 도구를 제공하는 MCP 서버. (위험 — 승인 필요)"""

    def __init__(self) -> None:
        super().__init__("automation")

    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="click",
                description=(
                    "지정한 화면 좌표를 마우스로 클릭합니다. "
                    "좌표는 screen.find_ui_element 로 먼저 확인하세요. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "x": {"type": "integer", "description": "클릭할 X 좌표"},
                        "y": {"type": "integer", "description": "클릭할 Y 좌표"},
                        "button": {
                            "type": "string",
                            "description": "마우스 버튼",
                            "enum": ["left", "right", "middle"],
                            "default": "left",
                        },
                    },
                    "required": ["x", "y"],
                },
            ),
            Tool(
                name="type_text",
                description=(
                    "현재 포커스된 입력창에 텍스트를 입력합니다. "
                    "먼저 입력창을 클릭해 포커스를 준 뒤 사용하세요. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "입력할 텍스트"}
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="key_press",
                description=(
                    "키보드 키를 누릅니다. 예: 'enter', 'tab', 'ctrl+c'. "
                    "시스템 종료·잠금 관련 조합은 사용할 수 없습니다. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "누를 키 이름 또는 조합 (예: enter, ctrl+c)",
                        }
                    },
                    "required": ["key"],
                },
            ),
            Tool(
                name="open_browser",
                description=(
                    "브라우저로 지정한 주소를 엽니다. "
                    "회사가 허용한 도메인만 열 수 있습니다. "
                    "⚠️ 사용자 승인 후에만 실행됩니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "열려는 웹 주소"}
                    },
                    "required": ["url"],
                },
            ),
        ]

    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다."""
        if name == "click":
            return self._click(
                int(arguments["x"]), int(arguments["y"]), arguments.get("button", "left")
            )
        if name == "type_text":
            return self._type_text(arguments["text"])
        if name == "key_press":
            return self._key_press(arguments["key"])
        if name == "open_browser":
            return self._open_browser(arguments["url"])
        raise MCPToolError(f"automation 서버에 '{name}' 도구가 없습니다.")

    # ------------------------------------------------------------
    # 개별 도구 구현
    # ------------------------------------------------------------
    def _click(self, x: int, y: int, button: str) -> dict[str, Any]:
        """지정 좌표를 클릭한다."""
        x, y, button_clean = validate_click(x, y, button, get_screen_size())
        pyautogui = _load_pyautogui()

        try:
            pyautogui.click(x=x, y=y, button=button_clean)
        except Exception as exc:
            raise MCPToolError(f"클릭에 실패했습니다: {exc}") from exc

        return {
            "x": x,
            "y": y,
            "button": button_clean,
            "message": f"({x}, {y}) 위치를 {button_clean} 버튼으로 클릭했습니다.",
        }

    def _type_text(self, text: str) -> dict[str, Any]:
        """포커스된 입력창에 텍스트를 입력한다."""
        validated = validate_text(text)
        pyautogui = _load_pyautogui()

        try:
            # 한글 등 비ASCII 문자는 typewrite 로 입력되지 않으므로
            # 클립보드를 거치지 않는 write 대신 안전한 경로를 쓴다.
            pyautogui.write(validated, interval=0.01)
        except Exception as exc:
            raise MCPToolError(
                f"텍스트 입력에 실패했습니다: {exc}\n"
                f"(한글 입력이 필요한 경우 입력기 설정을 확인하세요)"
            ) from exc

        preview = validated if len(validated) <= 30 else validated[:30] + "…"
        return {
            "length": len(validated),
            "message": f"텍스트를 입력했습니다: {preview}",
        }

    def _key_press(self, key: str) -> dict[str, Any]:
        """키를 누른다. (조합키 지원)"""
        keys = parse_key_combo(key)
        ensure_key_allowed(keys)
        pyautogui = _load_pyautogui()

        try:
            if len(keys) == 1:
                pyautogui.press(keys[0])
            else:
                pyautogui.hotkey(*keys)
        except Exception as exc:
            raise MCPToolError(f"키 입력에 실패했습니다: {exc}") from exc

        combo = "+".join(keys)
        return {"key": combo, "message": f"'{combo}' 키를 눌렀습니다."}

    def _open_browser(self, url: str) -> dict[str, Any]:
        """브라우저로 주소를 연다. (화이트리스트 검사)"""
        allowed, reason = check_url(url)
        if not allowed:
            raise MCPToolError(reason)

        target = url.strip()
        if "://" not in target:
            target = f"https://{target}"

        try:
            opened = webbrowser.open(target)
        except Exception as exc:
            raise MCPToolError(f"브라우저를 열지 못했습니다: {exc}") from exc

        if not opened:
            raise MCPToolError(
                "브라우저를 열지 못했습니다. "
                "기본 브라우저가 설정되어 있는지 확인하세요."
            )

        return {"url": target, "message": f"브라우저로 {target} 을(를) 열었습니다."}


def main() -> None:
    """단독 실행 진입점."""
    AutomationMCPServer.main()


if __name__ == "__main__":
    main()
