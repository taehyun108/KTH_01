"""
Kill Switch — 비상 정지.

두 가지 경로로 동작한다.

1. **전역 키보드 훅 (ESC)** — 어떤 창이 떠 있어도 동작
   `keyboard` 라이브러리를 사용한다. Windows 배포 환경이 주 대상이다.

2. **API / 화면 버튼** — `/api/agent/kill`
   전역 훅을 쓸 수 없는 환경에서도 반드시 중단할 수 있어야 한다.

⚠️ 플랫폼 제약
--------------
`keyboard` 라이브러리는 OS 마다 요구사항이 다르다.
  - Windows: 별도 권한 없이 동작 (배포 대상)
  - Linux  : root 권한 필요 → 권한이 없으면 훅 등록 실패
  - macOS  : 접근성 권한 필요

훅 등록에 실패해도 **앱은 정상 기동해야 한다.**
대신 `available=False` 로 표시해 프론트엔드가 "ESC 사용 불가, 화면의 정지 버튼을
사용하세요"라고 안내할 수 있게 한다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("pfm-agent.kill_switch")


class KillSwitch:
    """
    전역 비상 정지 스위치.

    Example:
        switch = KillSwitch(key="esc", on_trigger=run_manager.kill_all)
        switch.start()
        ...
        switch.stop()
    """

    def __init__(
        self,
        *,
        key: str = "esc",
        on_trigger: Callable[[], Any] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """
        Args:
            key: 비상 정지 키 (.env 의 KILL_SWITCH_KEY)
            on_trigger: 정지 시 호출할 함수 (보통 RunManager.kill_all)
            loop: 콜백을 실행할 이벤트 루프. 생략 시 start() 시점의 루프를 사용한다.
        """
        self.key = key
        self.on_trigger = on_trigger
        self._loop = loop
        self._hook: Any = None
        self._available = False
        self._unavailable_reason = ""
        self._trigger_count = 0

    # ------------------------------------------------------------
    # 상태
    # ------------------------------------------------------------
    @property
    def available(self) -> bool:
        """전역 키보드 훅이 활성화되어 있는지 여부."""
        return self._available

    @property
    def unavailable_reason(self) -> str:
        """훅을 쓸 수 없는 이유 (사용자 안내용 한글 메시지)."""
        return self._unavailable_reason

    @property
    def trigger_count(self) -> int:
        """정지가 발동된 횟수. (테스트/모니터링용)"""
        return self._trigger_count

    def status(self) -> dict[str, Any]:
        """상태 요약. (`/api/status` 응답용)"""
        return {
            "key": self.key,
            "global_hook_available": self._available,
            "reason": self._unavailable_reason,
            "trigger_count": self._trigger_count,
        }

    # ------------------------------------------------------------
    # 시작 / 종료
    # ------------------------------------------------------------
    def start(self) -> bool:
        """
        전역 키보드 훅을 등록한다.

        실패해도 예외를 던지지 않는다. (앱 기동을 막으면 안 됨)

        Returns:
            훅 등록에 성공했으면 True
        """
        if self._available:
            return True

        try:
            self._loop = self._loop or asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        try:
            import keyboard  # 지연 import: 설치/권한 문제를 여기서만 처리
        except ImportError as exc:
            self._unavailable_reason = (
                "keyboard 라이브러리가 설치되어 있지 않아 ESC 전역 단축키를 "
                "사용할 수 없습니다. 화면의 정지 버튼을 사용하세요."
            )
            logger.warning("Kill Switch 훅 사용 불가: %s", exc)
            return False

        try:
            self._hook = keyboard.add_hotkey(self.key, self.trigger)
            self._available = True
            self._unavailable_reason = ""
            logger.info("Kill Switch 전역 단축키 등록 완료: %s", self.key.upper())
            return True
        except Exception as exc:  # noqa: BLE001 - OS/권한 문제를 모두 흡수
            self._unavailable_reason = (
                f"ESC 전역 단축키를 등록하지 못했습니다 ({exc}). "
                f"화면의 정지 버튼을 사용하세요."
            )
            logger.warning("Kill Switch 훅 등록 실패: %s", exc)
            return False

    def stop(self) -> None:
        """전역 훅을 해제한다."""
        if self._hook is None:
            self._available = False
            return

        try:
            import keyboard

            keyboard.remove_hotkey(self._hook)
        except Exception as exc:  # noqa: BLE001 - 종료 중 오류는 무시
            logger.debug("Kill Switch 훅 해제 중 오류: %s", exc)
        finally:
            self._hook = None
            self._available = False

    # ------------------------------------------------------------
    # 발동
    # ------------------------------------------------------------
    def trigger(self) -> None:
        """
        비상 정지를 발동한다.

        ⚠️ 키보드 훅은 **별도 스레드**에서 호출되므로,
           이벤트 루프에 안전하게 전달해야 한다.
        """
        self._trigger_count += 1
        logger.warning("🛑 Kill Switch 발동 (%s)", self.key.upper())

        if self.on_trigger is None:
            return

        loop = self._loop
        if loop is not None and loop.is_running():
            # 다른 스레드에서 호출되어도 안전하게 루프에 전달한다.
            loop.call_soon_threadsafe(self._invoke)
        else:
            self._invoke()

    def _invoke(self) -> None:
        """정지 콜백을 실행한다."""
        if self.on_trigger is None:
            return
        try:
            result = self.on_trigger()
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception as exc:  # noqa: BLE001 - 정지 처리 실패를 로그로만 남긴다
            logger.error("Kill Switch 처리 중 오류: %s", exc)
