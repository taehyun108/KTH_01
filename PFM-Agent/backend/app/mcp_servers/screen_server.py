"""
screen MCP 서버 — 화면 인식 도구. (STEP 6 구현)

제공 도구:
  - capture_screen(region)      : 화면 캡처 → PNG 저장
  - find_ui_element(description): 화면에서 UI 요소 위치 탐지
  - ocr_region(bbox)            : 지정 영역 텍스트 인식

의존성 처리 원칙
----------------
화면 캡처/OCR 라이브러리는 **실행 환경에 크게 의존**한다.
  - 화면 캡처: 디스플레이가 있어야 함 (서버/헤드리스 환경에서는 불가)
  - OCR      : PaddleOCR + 로컬 모델 필요 (용량이 커서 선택 설치)

따라서 모두 **지연 import** 하고, 사용할 수 없을 때는
"왜 안 되는지 + 어떻게 해결하는지"를 한글로 안내한다.
서버 자체는 항상 정상 기동한다.

선택 의존성 설치:
    uv sync --extra vision

단독 실행:
    python -m app.mcp_servers.screen_server
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.types import Tool

from app.mcp_servers.base_server import (
    PROJECT_ROOT,
    BaseMCPServer,
    MCPToolError,
    to_relative,
)

logger = logging.getLogger("pfm-agent.mcp.screen")

#: 캡처 이미지를 저장할 폴더 (프로젝트 내부 — 포터블 원칙)
SCREENSHOT_DIR: Path = PROJECT_ROOT / "data" / "screenshots"

#: 보관할 최대 캡처 파일 수 (USB 용량 보호)
MAX_SCREENSHOTS: int = 50

#: list_ui_elements 가 기본으로 반환하는 요소 수.
#: (Agent 프롬프트에 들어가므로 너무 많으면 토큰을 낭비한다)
DEFAULT_ELEMENT_LIMIT: int = 60

#: list_ui_elements 가 반환할 수 있는 요소 수 상한
MAX_ELEMENT_LIMIT: int = 200

#: OCR 모델 경로 (STEP 10 에서 다운로드)
#: 하위에 det / rec / cls 폴더가 들어간다. **반드시 프로젝트 내부**여야 한다.
#: (홈 폴더에 두면 USB 로 옮길 때 따라오지 않아 폐쇄망에서 OCR 이 죽는다)
OCR_MODEL_DIR: Path = PROJECT_ROOT / "models" / "ocr"


# ============================================================
# 순수 로직 (환경에 의존하지 않아 단독 테스트 가능)
# ============================================================


def validate_region(region: list[int] | None) -> tuple[int, int, int, int] | None:
    """
    캡처 영역 [x, y, width, height] 를 검증한다.

    Returns:
        검증된 (x, y, width, height), region 이 없으면 None

    Raises:
        MCPToolError: 값이 잘못된 경우
    """
    if region is None:
        return None

    if len(region) != 4:
        raise MCPToolError(
            f"영역은 [x, y, 너비, 높이] 4개 값이어야 합니다. (받은 값: {region})"
        )

    x, y, width, height = (int(value) for value in region)

    if width <= 0 or height <= 0:
        raise MCPToolError(f"영역의 너비와 높이는 0보다 커야 합니다. (받은 값: {region})")
    if x < 0 or y < 0:
        raise MCPToolError(f"영역의 좌표는 0 이상이어야 합니다. (받은 값: {region})")

    return x, y, width, height


def validate_bbox(bbox: list[int]) -> tuple[int, int, int, int]:
    """
    OCR 영역 [x1, y1, x2, y2] 를 검증한다.

    Raises:
        MCPToolError: 값이 잘못된 경우
    """
    if len(bbox) != 4:
        raise MCPToolError(
            f"영역은 [x1, y1, x2, y2] 4개 값이어야 합니다. (받은 값: {bbox})"
        )

    x1, y1, x2, y2 = (int(value) for value in bbox)

    if x2 <= x1 or y2 <= y1:
        raise MCPToolError(
            f"영역의 오른쪽/아래 좌표가 왼쪽/위보다 커야 합니다. (받은 값: {bbox})"
        )
    if x1 < 0 or y1 < 0:
        raise MCPToolError(f"영역의 좌표는 0 이상이어야 합니다. (받은 값: {bbox})")

    return x1, y1, x2, y2


def score_text_match(needle: str, haystack: str) -> float:
    """
    자연어 설명과 화면 텍스트의 일치도를 0~1 로 계산한다.

    OmniParser 없이 OCR 결과만으로 UI 요소를 찾을 때 사용하는 간단한 점수.
      - 완전 일치      : 1.0
      - 포함 관계      : 0.8
      - 단어 부분 일치 : 겹치는 단어 비율

    조사/접미사("버튼", "창" 등)는 제거하고 비교한다.
    """
    needle_clean = _strip_ui_suffix(needle.strip().lower())
    haystack_clean = haystack.strip().lower()

    if not needle_clean or not haystack_clean:
        return 0.0
    if needle_clean == haystack_clean:
        return 1.0
    if needle_clean in haystack_clean or haystack_clean in needle_clean:
        return 0.8

    needle_words = set(needle_clean.split())
    haystack_words = set(haystack_clean.split())
    if not needle_words:
        return 0.0

    overlap = needle_words & haystack_words
    return len(overlap) / len(needle_words)


def _strip_ui_suffix(text: str) -> str:
    """'검색 버튼' → '검색' 처럼 UI 요소 종류 표현을 제거한다."""
    suffixes = ("버튼", "입력창", "입력란", "링크", "메뉴", "탭", "아이콘", "창", "칸")
    result = text
    for suffix in suffixes:
        if result.endswith(suffix):
            result = result[: -len(suffix)].strip()
            break
    return result


def bbox_center(bbox: tuple[int, int, int, int]) -> tuple[int, int]:
    """영역의 중심 좌표를 구한다. (클릭 지점)"""
    x1, y1, x2, y2 = bbox
    return (x1 + x2) // 2, (y1 + y2) // 2


def prune_old_screenshots(directory: Path, keep: int = MAX_SCREENSHOTS) -> int:
    """
    오래된 캡처 파일을 삭제한다. (USB 용량 보호)

    Returns:
        삭제한 파일 수
    """
    if not directory.is_dir():
        return 0

    files = sorted(
        (path for path in directory.glob("*.png") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for path in files[keep:]:
        path.unlink(missing_ok=True)
        removed += 1
    return removed


# ============================================================
# 환경 의존 기능 (지연 import)
# ============================================================


def _capture_error(exc: Exception) -> MCPToolError:
    """캡처 실패를 사용자용 한글 메시지로 감싼다."""
    return MCPToolError(
        "화면을 캡처할 수 없습니다.\n"
        "  - 원격 접속(SSH)이나 화면이 없는 환경에서는 캡처가 불가능합니다.\n"
        "  - 화면 잠금 상태에서도 실패할 수 있습니다.\n"
        f"  (상세: {exc})"
    )


def grab_screen(region: tuple[int, int, int, int] | None = None) -> Any:
    """
    화면을 캡처해 PIL Image 를 반환한다.

    `mss` → `PIL.ImageGrab` 순으로 시도한다.

    Raises:
        MCPToolError: 캡처 도구가 없거나 실패한 경우
    """
    # --- 1순위: mss (가볍고 빠름, Windows/Linux/macOS 지원) ---
    try:
        import mss
        from PIL import Image

        # mss.MSS 가 최신 API, 구버전은 mss.mss 만 제공한다.
        grabber_factory = getattr(mss, "MSS", None) or mss.mss
        with grabber_factory() as grabber:
            if region is None:
                monitor = grabber.monitors[0]  # 전체 화면
            else:
                x, y, width, height = region
                monitor = {"left": x, "top": y, "width": width, "height": height}
            raw = grabber.grab(monitor)
            return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    except ImportError:
        pass  # mss 가 없으면 2순위로 넘어간다
    except Exception as exc:  # noqa: BLE001 - 캡처 실패 시에도 2순위를 시도한다
        logger.debug("mss 캡처 실패, PIL.ImageGrab 으로 재시도합니다: %s", exc)

    # --- 2순위: PIL.ImageGrab (Windows/macOS) ---
    try:
        from PIL import ImageGrab

        bbox = None
        if region is not None:
            x, y, width, height = region
            bbox = (x, y, x + width, y + height)
        return ImageGrab.grab(bbox=bbox)
    except ImportError as exc:
        raise MCPToolError(
            "화면 캡처 라이브러리가 설치되어 있지 않습니다.\n"
            "  해결: first_time_setup.bat 를 다시 실행하거나 "
            "`uv sync --extra vision` 을 실행하세요."
        ) from exc
    except Exception as exc:
        raise _capture_error(exc) from exc


def ocr_model_dirs() -> dict[str, str]:
    """
    PaddleOCR 에 넘길 **프로젝트 내부** 모델 경로를 만든다.

    ⚠️ 왜 명시적으로 넘기는가 (포터블 / 폐쇄망 필수)
    ------------------------------------------------
    PaddleOCR 은 모델 경로를 지정하지 않으면 **사용자 홈 폴더**(`~/.paddleocr`)
    에서 모델을 찾고, 없으면 **인터넷에서 내려받으려 한다.**
    그러면 두 가지가 깨진다.

      1. USB 로 폴더째 옮겨도 모델이 따라오지 않는다. (홈 폴더에 있으므로)
      2. 폐쇄망 PC 에서는 다운로드가 막혀 화면 인식이 아예 동작하지 않는다.

    그래서 det / rec / cls 모델 경로를 **항상 프로젝트 폴더 하위로 명시**한다.
    """
    return {
        "det_model_dir": str(OCR_MODEL_DIR / "det"),
        "rec_model_dir": str(OCR_MODEL_DIR / "rec"),
        "cls_model_dir": str(OCR_MODEL_DIR / "cls"),
    }


def build_ocr_engine(lang: str = "korean") -> Any:
    """
    PaddleOCR 엔진을 만든다. (모델 경로를 프로젝트 내부로 고정)

    Raises:
        MCPToolError: OCR 라이브러리를 쓸 수 없는 경우
    """
    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise MCPToolError(
            "글자 인식(OCR) 기능이 설치되어 있지 않습니다.\n"
            "  해결: `uv sync --extra vision` 을 실행해 OCR 라이브러리를 설치하세요.\n"
            "  (폐쇄망에서는 담당자가 모델이 포함된 USB 를 전달해야 합니다)"
        ) from exc

    return PaddleOCR(lang=lang, show_log=False, **ocr_model_dirs())


#: 언어별 OCR 엔진 캐시.
#: PaddleOCR 생성은 **모델 파일을 읽어 들이는 무거운 작업**(수 초)이므로
#: 호출마다 새로 만들면 화면 인식이 극단적으로 느려진다. 한 번만 만들어 재사용한다.
_ocr_engines: dict[str, Any] = {}


def get_ocr_engine(lang: str = "korean") -> Any:
    """캐시된 OCR 엔진을 반환한다. (없으면 만들어 캐시)"""
    engine = _ocr_engines.get(lang)
    if engine is None:
        engine = build_ocr_engine(lang)
        _ocr_engines[lang] = engine
    return engine


def run_ocr(image: Any, lang: str = "korean") -> list[dict[str, Any]]:
    """
    이미지에서 텍스트를 인식한다. (PaddleOCR)

    Returns:
        [{"text": str, "bbox": [x1, y1, x2, y2], "confidence": float}, ...]

    Raises:
        MCPToolError: OCR 을 사용할 수 없는 경우
    """
    engine = get_ocr_engine(lang)

    try:
        import numpy as np

        result = engine.ocr(np.array(image), cls=True)
    except Exception as exc:
        raise MCPToolError(
            f"글자 인식에 실패했습니다: {exc}\n"
            f"  모델 파일이 {to_relative(OCR_MODEL_DIR)} 아래 "
            f"det / rec / cls 폴더에 있는지 확인하세요.\n"
            f"  (인터넷 되는 PC 에서 `python scripts/download_models.py` 로 받아 "
            f"models 폴더째 USB 로 옮기면 됩니다)"
        ) from exc

    items: list[dict[str, Any]] = []
    for line in result or []:
        for entry in line or []:
            try:
                points, (text, confidence) = entry
                xs = [int(point[0]) for point in points]
                ys = [int(point[1]) for point in points]
                items.append(
                    {
                        "text": text,
                        "bbox": [min(xs), min(ys), max(xs), max(ys)],
                        "confidence": round(float(confidence), 3),
                    }
                )
            except (ValueError, TypeError, IndexError):
                continue
    return items


# ============================================================
# MCP 서버
# ============================================================


class ScreenMCPServer(BaseMCPServer):
    """화면 캡처 / UI 요소 탐지 / OCR 도구를 제공하는 MCP 서버."""

    def __init__(self) -> None:
        super().__init__("screen")

    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="capture_screen",
                description=(
                    "현재 화면을 캡처해 이미지 파일로 저장하고 경로와 크기를 반환합니다. "
                    "PC 화면 상태를 확인해야 조작을 결정할 수 있을 때 가장 먼저 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "region": {
                            "type": "array",
                            "description": (
                                "캡처할 영역 [x, y, 너비, 높이]. "
                                "생략하면 전체 화면을 캡처합니다."
                            ),
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        }
                    },
                    "required": [],
                },
            ),
            Tool(
                name="find_ui_element",
                description=(
                    "화면에서 자연어 설명과 일치하는 UI 요소(버튼/입력창/링크 등)를 찾아 "
                    "클릭할 좌표를 반환합니다. 예: '검색 버튼', '주소 입력창'. "
                    "automation.click 을 쓰기 전에 좌표를 알아낼 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "찾을 UI 요소에 대한 자연어 설명",
                        }
                    },
                    "required": ["description"],
                },
            ),
            Tool(
                name="list_ui_elements",
                description=(
                    "현재 화면에서 인식되는 **모든** UI 요소(글자)와 클릭 좌표를 "
                    "목록으로 반환합니다. 무엇을 눌러야 할지 아직 모를 때, "
                    "화면 전체를 훑어보고 다음 조작을 결정하기 위해 사용하세요. "
                    "찾을 대상이 이미 정해져 있다면 find_ui_element 가 더 적합합니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": (
                                f"반환할 최대 요소 수 (기본 {DEFAULT_ELEMENT_LIMIT}, "
                                f"최대 {MAX_ELEMENT_LIMIT})"
                            ),
                            "minimum": 1,
                        }
                    },
                    "required": [],
                },
            ),
            Tool(
                name="ocr_region",
                description=(
                    "화면의 지정한 영역에서 텍스트를 인식해 반환합니다. "
                    "화면에 표시된 문자를 읽어야 할 때 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "bbox": {
                            "type": "array",
                            "description": "인식할 영역 [x1, y1, x2, y2]",
                            "items": {"type": "integer"},
                            "minItems": 4,
                            "maxItems": 4,
                        }
                    },
                    "required": ["bbox"],
                },
            ),
        ]

    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다."""
        if name == "capture_screen":
            return self._capture_screen(arguments.get("region"))
        if name == "find_ui_element":
            return self._find_ui_element(arguments["description"])
        if name == "list_ui_elements":
            return self._list_ui_elements(arguments.get("limit"))
        if name == "ocr_region":
            return self._ocr_region(arguments["bbox"])
        raise MCPToolError(f"screen 서버에 '{name}' 도구가 없습니다.")

    # ------------------------------------------------------------
    # 개별 도구 구현
    # ------------------------------------------------------------
    def _capture_screen(self, region: list[int] | None) -> dict[str, Any]:
        """화면을 캡처해 PNG 로 저장한다."""
        validated = validate_region(region)
        image = grab_screen(validated)

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        path = SCREENSHOT_DIR / f"screen_{timestamp}.png"
        image.save(path)

        prune_old_screenshots(SCREENSHOT_DIR)

        return {
            "path": to_relative(path),
            "width": image.width,
            "height": image.height,
            "message": f"화면을 캡처했습니다 ({image.width}x{image.height})",
        }

    def _find_ui_element(self, description: str) -> dict[str, Any]:
        """
        화면에서 설명과 일치하는 UI 요소를 찾는다.

        OCR 로 화면의 글자를 모두 읽은 뒤, 설명과 가장 잘 맞는 항목을 고른다.
        """
        if not description.strip():
            raise MCPToolError("찾을 UI 요소에 대한 설명을 입력하세요.")

        image = grab_screen(None)
        items = run_ocr(image)

        if not items:
            raise MCPToolError(
                "화면에서 글자를 찾지 못했습니다. "
                "창이 열려 있는지, 화면이 잠겨 있지 않은지 확인하세요."
            )

        scored = [
            (score_text_match(description, item["text"]), item) for item in items
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        best_score, best = scored[0]

        if best_score <= 0:
            found = ", ".join(item["text"] for item in items[:10])
            raise MCPToolError(
                f"'{description}' 과(와) 일치하는 요소를 찾지 못했습니다.\n"
                f"화면에서 인식된 글자: {found}"
            )

        x, y = bbox_center(tuple(best["bbox"]))  # type: ignore[arg-type]
        return {
            "found": True,
            "text": best["text"],
            "bbox": best["bbox"],
            "x": x,
            "y": y,
            "match_score": round(best_score, 3),
            "message": f"'{best['text']}' 을(를) ({x}, {y}) 위치에서 찾았습니다.",
        }

    def _list_ui_elements(self, limit: int | None) -> dict[str, Any]:
        """
        화면의 모든 UI 요소와 클릭 좌표를 목록으로 반환한다.

        GUI 자동 조작 루프에서 **"지금 화면에 무엇이 있는지"** 를 Agent 에게
        보여주기 위한 도구다. 요소가 지나치게 많으면 프롬프트가 커지므로
        위쪽(화면 상단) 순서로 정렬해 상한만큼만 돌려준다.
        """
        count = DEFAULT_ELEMENT_LIMIT if limit is None else int(limit)
        count = max(1, min(MAX_ELEMENT_LIMIT, count))

        image = grab_screen(None)
        items = run_ocr(image)

        if not items:
            raise MCPToolError(
                "화면에서 글자를 찾지 못했습니다. "
                "창이 열려 있는지, 화면이 잠겨 있지 않은지 확인하세요."
            )

        elements: list[dict[str, Any]] = []
        for item in items:
            x, y = bbox_center(tuple(item["bbox"]))  # type: ignore[arg-type]
            elements.append(
                {
                    "text": item["text"],
                    "x": x,
                    "y": y,
                    "confidence": item.get("confidence", 0.0),
                }
            )

        # 화면 위 → 아래, 왼쪽 → 오른쪽 순서로 정렬해 사람이 보는 순서와 맞춘다.
        elements.sort(key=lambda element: (element["y"], element["x"]))
        truncated = len(elements) > count

        return {
            "count": len(elements[:count]),
            "total": len(elements),
            "truncated": truncated,
            "width": image.width,
            "height": image.height,
            "elements": elements[:count],
            "message": (
                f"화면에서 요소 {len(elements)}개를 인식했습니다"
                + (f" (상위 {count}개만 반환)" if truncated else "")
            ),
        }

    def _ocr_region(self, bbox: list[int]) -> dict[str, Any]:
        """지정 영역의 텍스트를 인식한다."""
        x1, y1, x2, y2 = validate_bbox(bbox)
        image = grab_screen((x1, y1, x2 - x1, y2 - y1))
        items = run_ocr(image)

        return {
            "bbox": [x1, y1, x2, y2],
            "count": len(items),
            "text": "\n".join(item["text"] for item in items),
            "items": items,
        }


def main() -> None:
    """단독 실행 진입점."""
    ScreenMCPServer.main()


if __name__ == "__main__":
    main()
