"""
PFM-Agent 안전장치 패키지.

  - kill_switch   : 비상 정지 (ESC 전역 단축키 + API)
  - approval_gate : 위험 도구 실행 전 사용자 승인
  - undo_manager  : 되돌리기 스택
  - action_logger : 모든 액션을 ./logs/actions.jsonl 에 기록
"""

from app.safety.action_logger import ActionLogger, ActionRecord
from app.safety.approval_gate import ApprovalGate, PendingApproval
from app.safety.kill_switch import KillSwitch
from app.safety.undo_manager import (
    UndoAction,
    UndoError,
    UndoManager,
    make_file_undo_action,
)

__all__ = [
    "ActionLogger",
    "ActionRecord",
    "ApprovalGate",
    "KillSwitch",
    "PendingApproval",
    "UndoAction",
    "UndoError",
    "UndoManager",
    "make_file_undo_action",
]
