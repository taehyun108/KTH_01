"""
팀 협업 서비스 — 저장소 + 실시간 전달 + 기록.

역할
----
1. **비동기 래핑**  : SQLite 는 동기이므로 `asyncio.to_thread` 로 감싸
   이벤트 루프(화면 응답)를 막지 않는다.
2. **실시간 전달**  : 접속한 구성원들에게 WebSocket 으로 즉시 알린다.
3. **기록**         : 모든 활동을 `./logs/team.jsonl` 에 append-only 로 남긴다.

왜 기록을 두 곳에 남기는가
--------------------------
  - `data/team.db`   : 화면에 보여주고 검색하기 위한 **작업용** 저장소
  - `logs/team.jsonl`: 나중에 "무슨 일이 있었는지" 확인하기 위한 **감사용** 기록

DB 는 소프트 삭제로 내용이 가려질 수 있지만, JSONL 기록은 덧붙이기만 하므로
언제 누가 무엇을 했는지 추적할 수 있다. (회의록·감사 목적)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.team.store import (
    Attachment,
    Member,
    Message,
    Room,
    RoomKind,
    TeamStore,
    TeamStoreError,
)

logger = logging.getLogger("pfm-agent.team")

#: 구독자에게 이벤트를 전달하는 콜백 형태
Subscriber = Callable[[dict[str, Any]], Awaitable[None]]

#: 기록 파일이 이 크기를 넘으면 회전시킨다. (USB 용량 보호)
MAX_LOG_BYTES: int = 20 * 1024 * 1024

#: 보관할 회전 파일 개수
MAX_BACKUPS: int = 3


def _now() -> str:
    """ISO 8601 UTC 타임스탬프."""
    return datetime.now(UTC).isoformat()


class TeamService:
    """
    팀 협업 기능의 진입점.

    Example:
        service = TeamService(store, log_path=settings.log_dir / "team.jsonl")
        await service.start()
        room = await service.create_room("주간회의", kind="meeting", created_by="me")
        await service.send_text(room.id, "me", "회의 시작합니다")
    """

    def __init__(
        self,
        store: TeamStore,
        *,
        log_path: Path,
        max_attachment_bytes: int,
    ) -> None:
        """
        Args:
            store: 저장소
            log_path: 감사 기록 파일 경로 (프로젝트 내부)
            max_attachment_bytes: 첨부 파일 최대 크기
        """
        self.store = store
        self.log_path = Path(log_path)
        self.max_attachment_bytes = max_attachment_bytes
        # 방별 구독자 목록 (WebSocket 연결)
        self._subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------
    # 수명 주기
    # ------------------------------------------------------------
    async def start(self) -> None:
        """저장소를 준비한다. (앱 시작 시 1회)"""
        await asyncio.to_thread(self.store.ensure_schema)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("팀 협업 저장소 준비 완료: %s", self.store.db_path)

    async def stop(self) -> None:
        """저장소 연결을 정리한다."""
        await asyncio.to_thread(self.store.close)

    # ------------------------------------------------------------
    # 실시간 구독 (WebSocket)
    # ------------------------------------------------------------
    def subscribe(self, room_id: str) -> asyncio.Queue[dict[str, Any]]:
        """방의 실시간 이벤트를 구독한다."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(room_id, []).append(queue)
        return queue

    def unsubscribe(self, room_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """구독을 해제한다."""
        subscribers = self._subscribers.get(room_id)
        if subscribers and queue in subscribers:
            subscribers.remove(queue)
        if subscribers is not None and not subscribers:
            self._subscribers.pop(room_id, None)

    def subscriber_count(self, room_id: str) -> int:
        """현재 접속 중인 구독자 수. (상태 표시용)"""
        return len(self._subscribers.get(room_id, []))

    async def _broadcast(self, room_id: str, event: dict[str, Any]) -> None:
        """방 구독자 모두에게 이벤트를 전달한다."""
        for queue in list(self._subscribers.get(room_id, [])):
            await queue.put(event)

    # ------------------------------------------------------------
    # 기록 (append-only)
    # ------------------------------------------------------------
    async def _record(self, action: str, **payload: Any) -> None:
        """
        활동을 기록 파일에 남긴다.

        기록 실패가 대화를 막아서는 안 되므로 오류는 로그로만 남긴다.
        """
        entry = {"timestamp": _now(), "action": action, **payload}
        try:
            await asyncio.to_thread(self._append_log, entry)
        except OSError as exc:  # pragma: no cover - 디스크 문제 등
            logger.warning("팀 기록을 남기지 못했습니다: %s", exc)

    def _append_log(self, entry: dict[str, Any]) -> None:
        """JSON Lines 한 줄을 덧붙인다. (한글이 깨지지 않게 UTF-8)"""
        self._rotate_if_needed()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rotate_if_needed(self) -> None:
        """기록 파일이 너무 커지면 회전시킨다. (USB 용량 보호)"""
        if not self.log_path.is_file() or self.log_path.stat().st_size < MAX_LOG_BYTES:
            return

        oldest = self.log_path.with_suffix(self.log_path.suffix + f".{MAX_BACKUPS}")
        oldest.unlink(missing_ok=True)
        for index in range(MAX_BACKUPS - 1, 0, -1):
            source = self.log_path.with_suffix(self.log_path.suffix + f".{index}")
            if source.is_file():
                source.rename(
                    self.log_path.with_suffix(self.log_path.suffix + f".{index + 1}")
                )
        self.log_path.rename(self.log_path.with_suffix(self.log_path.suffix + ".1"))

    # ------------------------------------------------------------
    # 구성원
    # ------------------------------------------------------------
    async def register_member(self, member_id: str, display_name: str) -> Member:
        """구성원을 등록하거나 이름을 갱신한다."""
        member = await asyncio.to_thread(
            self.store.upsert_member, member_id, display_name
        )
        await self._record(
            "member_registered", member_id=member.id, display_name=member.display_name
        )
        return member

    async def list_members(self) -> list[Member]:
        """등록된 구성원 전체."""
        return await asyncio.to_thread(self.store.list_members)

    async def display_name(self, member_id: str) -> str:
        """구성원 표시 이름. (없으면 식별자를 그대로 사용)"""
        member = await asyncio.to_thread(self.store.get_member, member_id)
        return member.display_name if member else member_id

    # ------------------------------------------------------------
    # 방
    # ------------------------------------------------------------
    async def create_room(
        self,
        name: str,
        *,
        kind: RoomKind = "chat",
        created_by: str,
        member_ids: list[str] | None = None,
    ) -> Room:
        """대화방 또는 회의방을 만든다."""
        room = await asyncio.to_thread(
            self.store.create_room,
            name,
            kind=kind,
            created_by=created_by,
            member_ids=member_ids,
        )
        await self._record(
            "room_created",
            room_id=room.id,
            name=room.name,
            kind=room.kind,
            created_by=created_by,
        )
        # 방이 열렸음을 시스템 메시지로도 남긴다. (회의록에 시작 시각이 남는다)
        # 받침 유무에 따라 조사를 맞춘다. (회의**가** / 대화방**이**)
        opening = "회의가" if kind == "meeting" else "대화방이"
        await self.send_system(room.id, f"{opening} 시작되었습니다: {room.name}")
        return room

    async def list_rooms(self, *, member_id: str | None = None) -> list[Room]:
        """방 목록을 반환한다."""
        return await asyncio.to_thread(self.store.list_rooms, member_id=member_id)

    async def get_room(self, room_id: str) -> Room:
        """방 하나를 조회한다. (없으면 TeamStoreError)"""
        return await asyncio.to_thread(self.store.require_room, room_id)

    async def join_room(self, room_id: str, member_id: str) -> Room:
        """방에 참여한다."""
        room = await asyncio.to_thread(self.store.join_room, room_id, member_id)
        await self._record("room_joined", room_id=room_id, member_id=member_id)
        await self.send_system(
            room_id, f"{await self.display_name(member_id)} 님이 참여했습니다."
        )
        return room

    async def leave_room(self, room_id: str, member_id: str) -> Room:
        """방에서 나간다. (대화 기록은 남는다)"""
        name = await self.display_name(member_id)
        room = await asyncio.to_thread(self.store.leave_room, room_id, member_id)
        await self._record("room_left", room_id=room_id, member_id=member_id)
        await self.send_system(room_id, f"{name} 님이 나갔습니다.")
        return room

    async def close_room(self, room_id: str, member_id: str) -> Room:
        """
        회의를 종료한다.

        종료 후에는 메시지를 보낼 수 없지만 기록은 그대로 남는다.
        """
        await self.send_system(room_id, "회의가 종료되었습니다.")
        room = await asyncio.to_thread(self.store.close_room, room_id)
        await self._record("room_closed", room_id=room_id, member_id=member_id)
        await self._broadcast(room_id, {"type": "room_closed", "room": room.to_dict()})
        return room

    async def reopen_room(self, room_id: str, member_id: str) -> Room:
        """종료한 회의를 다시 연다."""
        room = await asyncio.to_thread(self.store.reopen_room, room_id)
        await self._record("room_reopened", room_id=room_id, member_id=member_id)
        await self.send_system(room_id, "회의가 다시 열렸습니다.")
        return room

    # ------------------------------------------------------------
    # 메시지
    # ------------------------------------------------------------
    async def send_text(self, room_id: str, member_id: str, body: str) -> Message:
        """글 메시지를 보낸다."""
        message = await asyncio.to_thread(
            self.store.add_message, room_id, member_id, body=body
        )
        await self._after_message(message)
        return message

    async def send_system(self, room_id: str, body: str) -> Message:
        """
        시스템 안내 메시지를 남긴다. (참여/퇴장/종료 등)

        보낸 사람은 `system` 으로 기록해 사람 메시지와 구분한다.
        """
        message = await asyncio.to_thread(
            self.store.add_message, room_id, "system", body=body, kind="system"
        )
        await self._after_message(message)
        return message

    async def send_file(
        self,
        room_id: str,
        member_id: str,
        *,
        filename: str,
        source: Path,
        body: str = "",
        move: bool = False,
    ) -> Message:
        """
        파일·이미지·영상을 보낸다.

        Args:
            filename: 상대에게 보여줄 원래 파일 이름
            source: 보낼 파일의 현재 위치
            body: 함께 보낼 설명 (선택)
            move: True 면 원본을 옮긴다. (업로드 임시 파일 정리용)
        """
        attachment = await asyncio.to_thread(
            self.store.store_attachment,
            room_id,
            member_id,
            filename=filename,
            source=source,
            max_bytes=self.max_attachment_bytes,
            move=move,
        )
        message = await asyncio.to_thread(
            self.store.add_message,
            room_id,
            member_id,
            body=body,
            attachment=attachment,
        )
        await self._after_message(message, attachment=attachment)
        return message

    async def _after_message(
        self, message: Message, *, attachment: Attachment | None = None
    ) -> None:
        """메시지 저장 후 기록 + 실시간 전달."""
        payload: dict[str, Any] = {
            "message_id": message.id,
            "room_id": message.room_id,
            "member_id": message.member_id,
            "kind": message.kind,
        }
        if attachment is not None:
            payload["filename"] = attachment.filename
            payload["size_bytes"] = attachment.size_bytes
            payload["sha256"] = attachment.sha256
        else:
            # 본문은 길 수 있으므로 기록에는 앞부분만 남긴다.
            payload["preview"] = message.body[:200]

        await self._record("message_sent", **payload)
        await self._broadcast(
            message.room_id, {"type": "message", "message": message.to_dict()}
        )

    async def list_messages(
        self, room_id: str, *, after_id: int = 0, limit: int = 100
    ) -> list[Message]:
        """방의 메시지를 오래된 순으로 반환한다."""
        await asyncio.to_thread(self.store.require_room, room_id)
        return await asyncio.to_thread(
            self.store.list_messages, room_id, after_id=after_id, limit=limit
        )

    async def delete_message(self, message_id: int, member_id: str) -> Message:
        """메시지를 삭제 표시한다. (기록은 남는다)"""
        message = await asyncio.to_thread(
            self.store.delete_message, message_id, member_id
        )
        await self._record(
            "message_deleted", message_id=message_id, member_id=member_id
        )
        await self._broadcast(
            message.room_id, {"type": "message_deleted", "message": message.to_dict()}
        )
        return message

    # ------------------------------------------------------------
    # 파일
    # ------------------------------------------------------------
    async def list_attachments(self, room_id: str) -> list[Attachment]:
        """방에서 주고받은 파일 목록."""
        await asyncio.to_thread(self.store.require_room, room_id)
        return await asyncio.to_thread(self.store.list_attachments, room_id)

    async def get_attachment(self, attachment_id: str) -> Attachment:
        """
        첨부 파일 정보를 조회한다.

        Raises:
            TeamStoreError: 파일이 없는 경우
        """
        attachment = await asyncio.to_thread(self.store.get_attachment, attachment_id)
        if attachment is None:
            raise TeamStoreError(f"'{attachment_id}' 첨부 파일을 찾을 수 없습니다.")
        return attachment

    def attachment_full_path(self, attachment: Attachment) -> Path:
        """
        첨부 파일의 실제 경로를 돌려준다.

        저장된 값은 프로젝트 기준 상대경로이므로 여기서 절대경로로 바꾼다.
        """
        return self.store.project_root / attachment.stored_path

    # ------------------------------------------------------------
    # 회의록
    # ------------------------------------------------------------
    async def build_transcript(self, room_id: str) -> str:
        """
        방의 전체 대화를 사람이 읽는 회의록(Markdown)으로 만든다.

        보고서로 남기거나 메일로 전달할 수 있는 형태다.
        """
        room = await self.get_room(room_id)
        members = {member.id: member.display_name for member in await self.list_members()}
        messages = await asyncio.to_thread(
            self.store.list_messages, room_id, after_id=0, limit=500
        )

        label = "회의록" if room.kind == "meeting" else "대화 기록"
        lines: list[str] = [
            f"# {room.name} {label}",
            "",
            f"- 시작: {room.created_at}",
            f"- 종료: {room.closed_at or '진행 중'}",
            f"- 참석자: {', '.join(members.get(m, m) for m in room.member_ids) or '없음'}",
            f"- 메시지 수: {room.message_count}건",
            "",
            "---",
            "",
        ]

        for message in messages:
            speaker = (
                "시스템"
                if message.kind == "system"
                else members.get(message.member_id, message.member_id)
            )
            time_text = message.created_at[11:19]  # HH:MM:SS

            if message.is_deleted:
                lines.append(f"- `{time_text}` **{speaker}**: _(삭제된 메시지)_")
                continue

            if message.attachment is not None:
                size_mb = message.attachment.size_bytes / 1024 / 1024
                kind_label = {"image": "이미지", "video": "영상", "file": "파일"}[
                    message.attachment.media_type
                ]
                detail = f"[{kind_label}] {message.attachment.filename} ({size_mb:.1f}MB)"
                body = f"{detail} {message.body}".strip()
            else:
                body = message.body

            lines.append(f"- `{time_text}` **{speaker}**: {body}")

        lines.extend(["", "---", "", "> PFM-Agent 가 자동으로 정리한 기록입니다."])
        return "\n".join(lines)

    async def stats(self) -> dict[str, int]:
        """저장 현황 요약."""
        return await asyncio.to_thread(self.store.stats)
