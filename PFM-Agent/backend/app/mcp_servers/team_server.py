"""
team MCP 서버 — 팀 대화방에 결과를 공유하는 도구.

Agent 가 만든 보고서를 팀 대화방에 바로 올리거나, 회의록을 정리해
남길 수 있게 한다. Agent 는 **반드시 이 MCP 서버를 통해서만** 팀 기능에
접근한다. (직접 함수 호출 금지 — 아키텍처 원칙)

제공 도구
---------
  - list_rooms()                       : 대화방 목록
  - post_message(room_id, body)        : 대화방에 글 남기기
  - share_file(room_id, path, message) : 파일/이미지/영상 공유
  - export_transcript(room_id)         : 회의록을 문서로 저장

⚠️ 안전
-------
파일 공유는 `safe_project_path()` 로 **프로젝트 폴더 하위만** 허용한다.
(사용자 PC 의 아무 파일이나 팀에 유출되는 것을 막는다)

단독 실행:
    python -m app.mcp_servers.team_server
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.types import Tool

from app.config.settings import get_settings
from app.mcp_servers.base_server import (
    BaseMCPServer,
    MCPToolError,
    safe_project_path,
    to_relative,
)
from app.team.service import TeamService
from app.team.store import TeamStore, TeamStoreError

logger = logging.getLogger("pfm-agent.mcp.team")

#: Agent 가 글을 남길 때 사용하는 식별자.
#: 사람이 보낸 메시지와 구분되도록 별도 이름을 쓴다.
AGENT_MEMBER_ID: str = "pfm-agent"

#: Agent 의 표시 이름
AGENT_DISPLAY_NAME: str = "PFM-Agent"

#: 회의록 저장 폴더 (프로젝트 내부 — 포터블 원칙)
TRANSCRIPT_DIR: str = "./output"


class TeamMCPServer(BaseMCPServer):
    """팀 협업 도구를 제공하는 MCP 서버."""

    def __init__(self) -> None:
        super().__init__("team")
        self._service: TeamService | None = None

    async def _get_service(self) -> TeamService:
        """
        팀 서비스를 준비한다. (첫 호출 때 한 번만)

        MCP 서버는 백엔드와 **별도 프로세스**이므로 같은 SQLite 파일을
        직접 열어 사용한다. (WAL 모드라 동시 접근이 안전하다)
        """
        if self._service is None:
            settings = get_settings()
            store = TeamStore(
                data_dir=settings.data_dir, project_root=settings.project_root
            )
            service = TeamService(
                store,
                log_path=settings.log_dir / "team.jsonl",
                max_attachment_bytes=settings.team_max_attachment_mb * 1024 * 1024,
            )
            await service.start()
            # Agent 자신을 구성원으로 등록해 두어야 이름이 제대로 표시된다.
            await service.register_member(AGENT_MEMBER_ID, AGENT_DISPLAY_NAME)
            self._service = service
        return self._service

    def get_tools(self) -> list[Tool]:
        """이 서버가 제공하는 도구 목록."""
        return [
            Tool(
                name="list_rooms",
                description=(
                    "팀 대화방/회의방 목록을 반환합니다. "
                    "결과를 어디에 공유할지 정하기 전에 먼저 호출해 "
                    "방 ID 를 확인하세요."
                ),
                inputSchema={"type": "object", "properties": {}, "required": []},
            ),
            Tool(
                name="post_message",
                description=(
                    "팀 대화방에 글을 남깁니다. 조사 결과 요약이나 진행 상황을 "
                    "구성원에게 알릴 때 사용하세요. 파일을 함께 보내려면 "
                    "share_file 을 사용하세요."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "room_id": {
                            "type": "string",
                            "description": "대화방 ID (list_rooms 로 확인)",
                        },
                        "body": {"type": "string", "description": "남길 내용"},
                    },
                    "required": ["room_id", "body"],
                },
            ),
            Tool(
                name="share_file",
                description=(
                    "팀 대화방에 파일·이미지·영상을 공유합니다. "
                    "생성한 보고서(Word/PPT)를 구성원에게 전달할 때 사용하세요. "
                    "프로젝트 폴더 안의 파일만 공유할 수 있습니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "room_id": {"type": "string", "description": "대화방 ID"},
                        "path": {
                            "type": "string",
                            "description": "공유할 파일 경로 (예: ./output/보고서.docx)",
                        },
                        "message": {
                            "type": "string",
                            "description": "파일과 함께 남길 설명 (선택)",
                        },
                    },
                    "required": ["room_id", "path"],
                },
            ),
            Tool(
                name="export_transcript",
                description=(
                    "대화방의 전체 기록을 회의록 문서로 저장합니다. "
                    "회의가 끝난 뒤 내용을 정리해 남길 때 사용하세요. "
                    "저장 경로를 반환합니다."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "room_id": {"type": "string", "description": "대화방 ID"},
                    },
                    "required": ["room_id"],
                },
            ),
        ]

    async def handle_call(self, name: str, arguments: dict[str, Any]) -> Any:
        """도구 호출을 처리한다."""
        try:
            if name == "list_rooms":
                return await self._list_rooms()
            if name == "post_message":
                return await self._post_message(
                    arguments["room_id"], arguments["body"]
                )
            if name == "share_file":
                return await self._share_file(
                    arguments["room_id"],
                    arguments["path"],
                    arguments.get("message", ""),
                )
            if name == "export_transcript":
                return await self._export_transcript(arguments["room_id"])
        except TeamStoreError as exc:
            # 저장소 오류는 이미 한글 안내이므로 그대로 전달한다.
            raise MCPToolError(str(exc)) from exc

        raise MCPToolError(f"team 서버에 '{name}' 도구가 없습니다.")

    # ------------------------------------------------------------
    # 개별 도구 구현
    # ------------------------------------------------------------
    async def _list_rooms(self) -> dict[str, Any]:
        """대화방 목록을 반환한다."""
        service = await self._get_service()
        rooms = await service.list_rooms()
        return {
            "count": len(rooms),
            "rooms": [
                {
                    "id": room.id,
                    "name": room.name,
                    "kind": room.kind,
                    "is_open": room.is_open,
                    "message_count": room.message_count,
                }
                for room in rooms
            ],
            "message": (
                f"대화방 {len(rooms)}개를 찾았습니다."
                if rooms
                else "아직 만들어진 대화방이 없습니다. 화면에서 먼저 방을 만들어 주세요."
            ),
        }

    async def _post_message(self, room_id: str, body: str) -> dict[str, Any]:
        """대화방에 글을 남긴다."""
        if not str(body).strip():
            raise MCPToolError("남길 내용을 입력하세요.")

        service = await self._get_service()
        message = await service.send_text(room_id, AGENT_MEMBER_ID, str(body))
        return {
            "message_id": message.id,
            "room_id": room_id,
            "created_at": message.created_at,
            "message": f"'{room_id}' 대화방에 글을 남겼습니다.",
        }

    async def _share_file(
        self, room_id: str, path: str, description: str
    ) -> dict[str, Any]:
        """
        파일을 대화방에 공유한다.

        보안: 프로젝트 폴더 하위 파일만 허용한다.
        """
        target = safe_project_path(path, must_exist=True)
        if not target.is_file():
            raise MCPToolError(f"파일이 아닙니다: {path}")

        service = await self._get_service()
        message = await service.send_file(
            room_id,
            AGENT_MEMBER_ID,
            filename=target.name,
            source=target,
            body=str(description or ""),
        )
        attachment = message.attachment
        assert attachment is not None  # send_file 은 항상 첨부를 만든다.

        return {
            "message_id": message.id,
            "room_id": room_id,
            "filename": attachment.filename,
            "media_type": attachment.media_type,
            "size_bytes": attachment.size_bytes,
            "message": (
                f"'{attachment.filename}' 을(를) '{room_id}' 대화방에 공유했습니다."
            ),
        }

    async def _export_transcript(self, room_id: str) -> dict[str, Any]:
        """회의록을 Markdown 파일로 저장한다."""
        service = await self._get_service()
        room = await service.get_room(room_id)
        transcript = await service.build_transcript(room_id)

        output_dir = safe_project_path(TRANSCRIPT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 파일명에 쓸 수 없는 문자를 정리한다.
        clean_name = "".join(
            char if char.isalnum() or char in " -_가-힣" else "_" for char in room.name
        ).strip()
        stamp = room.created_at[:10].replace("-", "")
        target = output_dir / f"{stamp}_{clean_name or room.id}_회의록.md"
        target.write_text(transcript, encoding="utf-8")

        return {
            "path": to_relative(target),
            "room_name": room.name,
            "message_count": room.message_count,
            "message": f"회의록을 저장했습니다: {to_relative(target)}",
        }


def main() -> None:
    """단독 실행 진입점."""
    TeamMCPServer.main()


if __name__ == "__main__":
    main()
