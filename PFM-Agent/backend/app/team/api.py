"""
팀 협업 API 라우터 (REST + WebSocket).

같은 그룹 구성원끼리 대화·회의·파일 공유를 하기 위한 엔드포인트다.

연결 방식 (폐쇄망)
------------------
한 PC 가 **호스트**로 백엔드를 열고, 다른 PC 들이 그 주소로 접속한다.
  - 호스트 PC   : `.env` 에 `TEAM_SERVER_ENABLED=true`
  - 참여자 PC   : `.env` 에 `TEAM_SERVER_URL=http://호스트IP:8756`

엔드포인트
----------
  GET    /api/team/me                       내 정보
  GET    /api/team/members                  구성원 목록
  GET    /api/team/rooms                    방 목록
  POST   /api/team/rooms                    방 만들기 (대화 / 회의)
  GET    /api/team/rooms/{id}               방 정보
  POST   /api/team/rooms/{id}/join          참여
  POST   /api/team/rooms/{id}/leave         나가기
  POST   /api/team/rooms/{id}/close         회의 종료
  GET    /api/team/rooms/{id}/messages      메시지 목록
  POST   /api/team/rooms/{id}/messages      글 보내기
  POST   /api/team/rooms/{id}/upload        파일/이미지/영상 보내기
  GET    /api/team/rooms/{id}/attachments   주고받은 파일 목록
  GET    /api/team/rooms/{id}/transcript    회의록 (Markdown)
  DELETE /api/team/messages/{id}            메시지 삭제 (기록은 남음)
  GET    /api/team/attachments/{id}/download 파일 내려받기
  WS     /ws/team/{room_id}                 실시간 수신
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from app.team.service import TeamService
from app.team.store import TeamStoreError

logger = logging.getLogger("pfm-agent.team.api")

#: 업로드를 읽어 들일 때의 조각 크기
UPLOAD_CHUNK: int = 1024 * 1024

#: WebSocket 연결 유지 확인 주기(초)
WS_PING_INTERVAL: float = 30.0


class CreateRoomRequest(BaseModel):
    """방 만들기 요청."""

    name: str = Field(..., min_length=1, description="방 이름")
    kind: str = Field(default="chat", description="chat(대화) 또는 meeting(회의)")
    member_ids: list[str] = Field(default_factory=list, description="초대할 구성원")


class SendMessageRequest(BaseModel):
    """글 보내기 요청."""

    body: str = Field(..., min_length=1, description="보낼 내용")


class RegisterMemberRequest(BaseModel):
    """구성원 등록/이름 변경 요청."""

    display_name: str = Field(..., min_length=1, description="표시할 이름")


class TeamContext:
    """
    라우터가 사용하는 팀 서비스 보관소.

    앱 시작 시 `bind()` 로 서비스를 넣어 준다. 준비되지 않은 상태에서
    호출되면 비개발자도 알아볼 수 있는 한글 안내를 돌려준다.
    """

    def __init__(self) -> None:
        self.service: TeamService | None = None
        self.member_id: str = ""
        self.display_name: str = ""
        self.disabled_reason: str = ""

    def bind(self, service: TeamService, *, member_id: str, display_name: str) -> None:
        """서비스를 연결한다."""
        self.service = service
        self.member_id = member_id
        self.display_name = display_name
        self.disabled_reason = ""

    def disable(self, reason: str) -> None:
        """기능을 사용할 수 없는 상태로 표시한다."""
        self.service = None
        self.disabled_reason = reason

    def require(self) -> TeamService:
        """
        서비스를 꺼낸다.

        Raises:
            HTTPException: 아직 준비되지 않았거나 꺼져 있는 경우
        """
        if self.service is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    self.disabled_reason
                    or "팀 협업 기능이 준비되지 않았습니다. 잠시 후 다시 시도하세요."
                ),
            )
        return self.service


#: 앱 전역에서 공유하는 컨텍스트
team_context = TeamContext()


def _bad_request(exc: TeamStoreError) -> HTTPException:
    """저장소 오류를 한글 그대로 사용자에게 전달한다."""
    return HTTPException(status_code=400, detail=str(exc))


def create_team_router() -> APIRouter:
    """팀 협업 라우터를 만든다."""
    router = APIRouter(prefix="/api/team", tags=["team"])

    # ------------------------------------------------------------
    # 내 정보 / 구성원
    # ------------------------------------------------------------
    @router.get("/me")
    async def me() -> dict[str, Any]:
        """내 식별자와 표시 이름."""
        return {
            "member_id": team_context.member_id,
            "display_name": team_context.display_name,
            "enabled": team_context.service is not None,
            "reason": team_context.disabled_reason,
        }

    @router.post("/me")
    async def update_me(request: RegisterMemberRequest) -> dict[str, Any]:
        """내 표시 이름을 바꾼다."""
        service = team_context.require()
        try:
            member = await service.register_member(
                team_context.member_id, request.display_name
            )
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        team_context.display_name = member.display_name
        return member.to_dict()

    @router.get("/members")
    async def members() -> dict[str, Any]:
        """등록된 구성원 목록."""
        service = team_context.require()
        found = await service.list_members()
        return {"count": len(found), "members": [item.to_dict() for item in found]}

    @router.get("/stats")
    async def stats() -> dict[str, Any]:
        """저장 현황 요약."""
        service = team_context.require()
        return await service.stats()

    # ------------------------------------------------------------
    # 방
    # ------------------------------------------------------------
    @router.get("/rooms")
    async def list_rooms(mine: bool = False) -> dict[str, Any]:
        """
        방 목록.

        Args:
            mine: True 면 내가 속한 방만
        """
        service = team_context.require()
        rooms = await service.list_rooms(
            member_id=team_context.member_id if mine else None
        )
        return {"count": len(rooms), "rooms": [room.to_dict() for room in rooms]}

    @router.post("/rooms")
    async def create_room(request: CreateRoomRequest) -> dict[str, Any]:
        """대화방 또는 회의방을 만든다."""
        service = team_context.require()
        try:
            room = await service.create_room(
                request.name,
                kind=request.kind,  # type: ignore[arg-type]
                created_by=team_context.member_id,
                member_ids=request.member_ids,
            )
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        return room.to_dict()

    @router.get("/rooms/{room_id}")
    async def get_room(room_id: str) -> dict[str, Any]:
        """방 정보."""
        service = team_context.require()
        try:
            room = await service.get_room(room_id)
        except TeamStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {**room.to_dict(), "online": service.subscriber_count(room_id)}

    @router.post("/rooms/{room_id}/join")
    async def join_room(room_id: str) -> dict[str, Any]:
        """방에 참여한다."""
        service = team_context.require()
        try:
            room = await service.join_room(room_id, team_context.member_id)
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        return room.to_dict()

    @router.post("/rooms/{room_id}/leave")
    async def leave_room(room_id: str) -> dict[str, Any]:
        """방에서 나간다. (대화 기록은 남는다)"""
        service = team_context.require()
        try:
            room = await service.leave_room(room_id, team_context.member_id)
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        return room.to_dict()

    @router.post("/rooms/{room_id}/close")
    async def close_room(room_id: str) -> dict[str, Any]:
        """회의를 종료한다."""
        service = team_context.require()
        try:
            room = await service.close_room(room_id, team_context.member_id)
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        return room.to_dict()

    @router.post("/rooms/{room_id}/reopen")
    async def reopen_room(room_id: str) -> dict[str, Any]:
        """종료한 회의를 다시 연다."""
        service = team_context.require()
        try:
            room = await service.reopen_room(room_id, team_context.member_id)
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        return room.to_dict()

    # ------------------------------------------------------------
    # 메시지
    # ------------------------------------------------------------
    @router.get("/rooms/{room_id}/messages")
    async def list_messages(
        room_id: str, after_id: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        """방의 메시지 목록. (오래된 순)"""
        service = team_context.require()
        try:
            messages = await service.list_messages(
                room_id, after_id=after_id, limit=limit
            )
        except TeamStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "count": len(messages),
            "messages": [message.to_dict() for message in messages],
        }

    @router.post("/rooms/{room_id}/messages")
    async def send_message(room_id: str, request: SendMessageRequest) -> dict[str, Any]:
        """글을 보낸다."""
        service = team_context.require()
        try:
            message = await service.send_text(
                room_id, team_context.member_id, request.body
            )
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        return message.to_dict()

    @router.delete("/messages/{message_id}")
    async def delete_message(message_id: int) -> dict[str, Any]:
        """
        메시지를 삭제한다.

        ⚠️ 화면에서만 가려지고 **기록은 그대로 남는다.** (감사 목적)
        """
        service = team_context.require()
        try:
            message = await service.delete_message(message_id, team_context.member_id)
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        return message.to_dict()

    # ------------------------------------------------------------
    # 파일 / 이미지 / 영상
    # ------------------------------------------------------------
    @router.post("/rooms/{room_id}/upload")
    async def upload(
        room_id: str,
        file: UploadFile = File(..., description="보낼 파일"),
        body: str = Form(default="", description="함께 보낼 설명"),
    ) -> dict[str, Any]:
        """
        파일·이미지·영상을 보낸다.

        업로드 내용을 임시 파일로 받은 뒤 저장소로 **옮긴다.**
        (메모리에 통째로 올리지 않아 큰 영상도 처리할 수 있다)
        """
        service = team_context.require()
        temp_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(delete=False) as handle:
                temp_path = Path(handle.name)
                while chunk := await file.read(UPLOAD_CHUNK):
                    handle.write(chunk)

            message = await service.send_file(
                room_id,
                team_context.member_id,
                filename=file.filename or "첨부파일",
                source=temp_path,
                body=body,
                move=True,  # 임시 파일을 옮겨 저장소에 보관
            )
        except TeamStoreError as exc:
            raise _bad_request(exc) from exc
        finally:
            # move=True 로 성공하면 이미 사라졌으므로 남은 경우만 정리한다.
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)

        return message.to_dict()

    @router.get("/rooms/{room_id}/attachments")
    async def list_attachments(room_id: str) -> dict[str, Any]:
        """방에서 주고받은 파일 목록."""
        service = team_context.require()
        try:
            found = await service.list_attachments(room_id)
        except TeamStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"count": len(found), "attachments": [item.to_dict() for item in found]}

    @router.get("/attachments/{attachment_id}/download")
    async def download(attachment_id: str) -> FileResponse:
        """파일을 내려받는다. (이미지/영상은 화면에서 바로 표시된다)"""
        service = team_context.require()
        try:
            attachment = await service.get_attachment(attachment_id)
        except TeamStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        path = service.attachment_full_path(attachment)
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail=(
                    f"'{attachment.filename}' 파일이 저장소에서 사라졌습니다. "
                    f"보낸 사람에게 다시 요청해 주세요."
                ),
            )
        return FileResponse(path, filename=attachment.filename)

    # ------------------------------------------------------------
    # 회의록
    # ------------------------------------------------------------
    @router.get("/rooms/{room_id}/transcript", response_class=PlainTextResponse)
    async def transcript(room_id: str) -> str:
        """방의 전체 기록을 회의록(Markdown)으로 반환한다."""
        service = team_context.require()
        try:
            return await service.build_transcript(room_id)
        except TeamStoreError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router


def create_team_websocket_route(application: Any) -> None:
    """
    실시간 수신 WebSocket 을 등록한다.

    접속하면 그 방의 새 메시지를 즉시 받는다.
    """

    @application.websocket("/ws/team/{room_id}")
    async def team_events(websocket: WebSocket, room_id: str) -> None:
        """방의 실시간 이벤트를 전달한다."""
        await websocket.accept()

        service = team_context.service
        if service is None:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": team_context.disabled_reason
                    or "팀 협업 기능이 준비되지 않았습니다.",
                }
            )
            await websocket.close()
            return

        queue = service.subscribe(room_id)
        try:
            await websocket.send_json({"type": "connected", "room_id": room_id})
            while True:
                try:
                    event = await asyncio.wait_for(
                        queue.get(), timeout=WS_PING_INTERVAL
                    )
                except TimeoutError:
                    # 연결이 살아 있는지 확인한다. (중간 장비가 끊는 것 방지)
                    await websocket.send_json({"type": "ping"})
                    continue
                await websocket.send_json(event)
        except WebSocketDisconnect:
            logger.debug("팀 WebSocket 연결 종료: %s", room_id)
        except Exception as exc:  # noqa: BLE001 - 연결 오류로 서버가 죽지 않게 한다
            logger.warning("팀 WebSocket 오류(%s): %s", room_id, exc)
        finally:
            service.unsubscribe(room_id, queue)
