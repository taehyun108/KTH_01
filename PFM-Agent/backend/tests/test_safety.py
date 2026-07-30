"""
STEP 5 검증: 안전장치 테스트.

  - Kill Switch  : ESC 전역 훅 + API 폴백
  - Approval Gate: 승인/거절/시간초과 자동 거절
  - Undo Manager : 파일 복원 / 되돌릴 수 없는 액션 구분
  - Action Logger: ./logs/actions.jsonl 기록

⚠️ 플랫폼 제약
   `keyboard` 전역 훅은 Linux 에서 root 권한이 필요해 이 환경에서는
   실제 키 입력을 검증할 수 없다. 따라서
     (1) 훅 등록 실패해도 앱이 죽지 않는지
     (2) 훅 없이도 수동 발동/ API 로 중단되는지
   를 검증한다. (배포 대상인 Windows 에서는 훅이 등록된다)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.safety.action_logger import ActionLogger, ActionRecord
from app.safety.approval_gate import ApprovalGate
from app.safety.kill_switch import KillSwitch
from app.safety.undo_manager import (
    UndoAction,
    UndoError,
    UndoManager,
    make_file_undo_action,
)

# ============================================================
# 1. Kill Switch
# ============================================================


def test_kill_switch_start_never_raises() -> None:
    """
    🔴 훅 등록에 실패해도 예외를 던지지 않아야 한다.
    (앱 기동을 막으면 안 됨 — 이 환경에서는 권한이 없어 실패가 정상)
    """
    switch = KillSwitch(key="esc")
    result = switch.start()  # 예외 없이 True/False 만 반환
    assert isinstance(result, bool)

    status = switch.status()
    assert status["key"] == "esc"
    assert isinstance(status["global_hook_available"], bool)

    # 훅을 못 쓰면 사용자 안내 문구가 있어야 한다.
    if not switch.available:
        assert "정지 버튼" in switch.unavailable_reason

    switch.stop()


def test_kill_switch_manual_trigger_calls_callback() -> None:
    """훅 없이 수동 발동해도 콜백이 호출되어야 한다. (API/버튼 경로)"""
    calls: list[int] = []

    switch = KillSwitch(key="esc", on_trigger=lambda: calls.append(1))
    switch.trigger()

    assert calls == [1]
    assert switch.trigger_count == 1


def test_kill_switch_callback_error_does_not_propagate() -> None:
    """정지 콜백이 실패해도 예외가 밖으로 나가면 안 된다."""

    def broken() -> None:
        raise RuntimeError("콜백 실패")

    switch = KillSwitch(key="esc", on_trigger=broken)
    switch.trigger()  # 예외가 나오면 테스트 실패
    assert switch.trigger_count == 1


def test_kill_switch_stop_is_safe_without_start() -> None:
    """시작하지 않은 상태에서 stop() 해도 안전해야 한다."""
    switch = KillSwitch(key="esc")
    switch.stop()
    assert switch.available is False


# ============================================================
# 2. Approval Gate
# ============================================================


async def test_approval_gate_approve() -> None:
    """승인하면 True 를 반환해야 한다."""
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(run_id: str, event_type: str, **payload: Any) -> None:
        events.append((event_type, payload))

    gate = ApprovalGate(emit=emit)
    task = asyncio.create_task(gate.request("run-1", "automation.click", {"x": 1}))

    for _ in range(50):
        await asyncio.sleep(0.01)
        if gate.pending:
            break

    approval = gate.pending[0]
    assert approval.tool_display == "automation.click"
    assert gate.resolve(approval.approval_id, True) is True

    assert await task is True

    event_types = [event_type for event_type, _ in events]
    assert "approval_required" in event_types
    assert "approval_resolved" in event_types


async def test_approval_gate_deny() -> None:
    """거절하면 False 를 반환해야 한다."""
    gate = ApprovalGate()
    task = asyncio.create_task(gate.request("run-1", "automation.click", {}))

    for _ in range(50):
        await asyncio.sleep(0.01)
        if gate.pending:
            break

    gate.resolve(gate.pending[0].approval_id, False)
    assert await task is False


async def test_approval_gate_timeout_denies() -> None:
    """
    🔴 안전 검증: 응답이 없으면 **자동 거절**되어야 한다.
    (사용자가 자리를 비웠을 때 무단 실행 방지)
    """
    gate = ApprovalGate(timeout=0.1)
    approved = await gate.request("run-1", "automation.click", {})
    assert approved is False


async def test_approval_gate_deny_all_for_run() -> None:
    """Kill Switch 발동 시 대기 중인 요청이 모두 거절되어야 한다."""
    gate = ApprovalGate()
    task_a = asyncio.create_task(gate.request("run-1", "automation.click", {}))
    task_b = asyncio.create_task(gate.request("run-1", "automation.type_text", {}))
    task_other = asyncio.create_task(gate.request("run-2", "automation.click", {}))

    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(gate.pending) == 3:
            break

    denied = gate.deny_all_for_run("run-1")
    assert denied == 2
    assert await task_a is False
    assert await task_b is False

    # 다른 실행은 영향을 받지 않아야 한다.
    assert len(gate.pending_for_run("run-2")) == 1
    gate.resolve(gate.pending[0].approval_id, True)
    assert await task_other is True


def test_approval_gate_resolve_unknown_returns_false() -> None:
    """없는 승인 요청을 처리하면 False 를 반환해야 한다."""
    gate = ApprovalGate()
    assert gate.resolve("없는-id", True) is False


# ============================================================
# 3. Undo Manager
# ============================================================


async def test_undo_restores_previous_file_content(tmp_path: Path) -> None:
    """파일 수정을 되돌리면 이전 내용이 복원되어야 한다."""
    target = tmp_path / "보고서.md"
    target.write_text("원래 내용", encoding="utf-8")

    manager = UndoManager()
    manager.push(make_file_undo_action(target, "원래 내용"))

    # 에이전트가 파일을 덮어썼다고 가정
    target.write_text("에이전트가 바꾼 내용", encoding="utf-8")

    description = await manager.undo_last()

    assert target.read_text(encoding="utf-8") == "원래 내용"
    assert "파일 수정" in description


async def test_undo_deletes_newly_created_file(tmp_path: Path) -> None:
    """새로 만든 파일을 되돌리면 삭제되어야 한다."""
    target = tmp_path / "새파일.md"

    manager = UndoManager()
    manager.push(make_file_undo_action(target, None))  # 이전 내용 없음 = 신규

    target.write_text("새로 만든 내용", encoding="utf-8")
    description = await manager.undo_last()

    assert not target.exists()
    assert "파일 생성" in description


async def test_undo_empty_stack_raises_korean_error() -> None:
    """되돌릴 것이 없으면 한글 안내와 함께 실패해야 한다."""
    manager = UndoManager()
    with pytest.raises(UndoError) as excinfo:
        await manager.undo_last()
    assert "되돌릴 작업이 없습니다" in str(excinfo.value)


async def test_undo_order_is_lifo(tmp_path: Path) -> None:
    """되돌리기는 최근 것부터 수행되어야 한다."""
    order: list[str] = []

    def make(name: str) -> UndoAction:
        async def _undo() -> None:
            order.append(name)

        return UndoAction(description=name, undo=_undo)

    manager = UndoManager()
    manager.push(make("첫번째"))
    manager.push(make("두번째"))

    await manager.undo_last()
    await manager.undo_last()

    assert order == ["두번째", "첫번째"]
    assert manager.can_undo is False


async def test_undo_failure_does_not_requeue(tmp_path: Path) -> None:
    """되돌리기에 실패한 액션은 스택에 다시 쌓이지 않아야 한다. (무한 재시도 방지)"""

    async def _broken() -> None:
        raise OSError("디스크 오류")

    manager = UndoManager()
    manager.push(UndoAction(description="망가진 액션", undo=_broken))

    with pytest.raises(UndoError) as excinfo:
        await manager.undo_last()

    assert "되돌리기에 실패" in str(excinfo.value)
    assert manager.can_undo is False  # 다시 쌓이지 않음


def test_undo_stack_has_max_size() -> None:
    """스택이 무한정 커지지 않아야 한다."""

    async def _noop() -> None:
        return None

    manager = UndoManager(max_size=3)
    for index in range(10):
        manager.push(UndoAction(description=f"액션{index}", undo=_noop))

    assert manager.size == 3
    # 최신 것이 남아 있어야 한다.
    assert manager.peek() is not None
    assert manager.peek().description == "액션9"


# ============================================================
# 4. Action Logger
# ============================================================


async def test_action_logger_writes_jsonl(tmp_path: Path) -> None:
    """액션이 JSON Lines 형식으로 기록되어야 한다."""
    log_path = tmp_path / "actions.jsonl"
    logger = ActionLogger(log_path)

    await logger.log(
        ActionRecord(
            run_id="run-1",
            step="executor",
            action="tool_call",
            tool="automation.click",
            arguments={"x": 10, "y": 20},
            ok=True,
            detail="클릭 완료",
        )
    )

    assert log_path.is_file()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["run_id"] == "run-1"
    assert record["tool"] == "automation.click"
    assert record["arguments"] == {"x": 10, "y": 20}
    assert record["ok"] is True


async def test_action_logger_preserves_korean(tmp_path: Path) -> None:
    """한글이 깨지지 않고 그대로 기록되어야 한다. (비개발자가 직접 열어봄)"""
    log_path = tmp_path / "actions.jsonl"
    logger = ActionLogger(log_path)

    await logger.log(
        ActionRecord(
            run_id="run-1",
            step="generator",
            action="tool_call",
            detail="소듐이온배터리 보고서를 저장했습니다",
        )
    )

    raw = log_path.read_text(encoding="utf-8")
    assert "소듐이온배터리 보고서를 저장했습니다" in raw  # \uXXXX 이스케이프 아님


async def test_action_logger_read_run_filters(tmp_path: Path) -> None:
    """특정 실행의 기록만 조회할 수 있어야 한다."""
    logger = ActionLogger(tmp_path / "actions.jsonl")

    await logger.log(ActionRecord(run_id="A", step="planner", action="tool_call"))
    await logger.log(ActionRecord(run_id="B", step="planner", action="tool_call"))
    await logger.log(ActionRecord(run_id="A", step="generator", action="tool_call"))

    assert len(logger.read_all()) == 3
    assert len(logger.read_run("A")) == 2
    assert len(logger.read_run("B")) == 1


async def test_action_logger_skips_corrupted_lines(tmp_path: Path) -> None:
    """형식이 깨진 줄이 있어도 나머지를 읽을 수 있어야 한다."""
    log_path = tmp_path / "actions.jsonl"
    logger = ActionLogger(log_path)

    await logger.log(ActionRecord(run_id="A", step="planner", action="tool_call"))
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("이건 JSON 이 아님\n")
    await logger.log(ActionRecord(run_id="B", step="planner", action="tool_call"))

    records = logger.read_all()
    assert len(records) == 2


async def test_action_logger_rotates_large_file(tmp_path: Path) -> None:
    """파일이 너무 커지면 회전되어야 한다. (USB 용량 보호)"""
    log_path = tmp_path / "actions.jsonl"
    logger = ActionLogger(log_path, max_bytes=200)

    for index in range(20):
        await logger.log(
            ActionRecord(
                run_id="A", step="planner", action="tool_call", detail=f"기록 {index}" * 5
            )
        )

    # 회전 파일이 만들어졌어야 한다.
    assert log_path.exists()
    assert (tmp_path / "actions.jsonl.1").exists()


async def test_action_logger_never_breaks_execution(tmp_path: Path) -> None:
    """
    🔴 기록 실패가 에이전트 실행을 막으면 안 된다.
    (쓰기 불가 경로를 줘도 예외가 나오지 않아야 함)
    """
    # 파일이 아니라 디렉터리를 경로로 주어 쓰기를 실패시킨다.
    bad_dir = tmp_path / "이건폴더"
    bad_dir.mkdir()

    logger = ActionLogger(bad_dir)
    await logger.log(ActionRecord(run_id="A", step="planner", action="tool_call"))
    # 예외 없이 통과하면 성공
