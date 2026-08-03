"""
팀 협업 기능 검증 (대화 / 회의 / 파일·이미지·영상 / 기록).

검증 항목
---------
1. 저장소 — 방·메시지·첨부파일 저장과 조회
2. 기록 보존 — 삭제해도 기록이 남는가 (감사 목적)
3. 보안 — 파일 이름으로 저장 위치를 벗어날 수 없는가
4. 용량 제한 — 큰 파일을 막는가
5. 회의 — 종료 후 메시지가 막히는가
6. 회의록 — 사람이 읽는 형태로 정리되는가
7. API — REST 엔드포인트가 동작하는가
8. 실시간 — WebSocket 으로 새 메시지가 전달되는가
9. MCP — Agent 가 도구로 대화방에 공유할 수 있는가
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.team.service import TeamService
from app.team.store import (
    TeamStore,
    TeamStoreError,
    classify_media,
    safe_filename,
)

#: 테스트용 첨부 크기 상한 (1MB)
SMALL_LIMIT = 1024 * 1024


# ============================================================
# 픽스처
# ============================================================


@pytest.fixture
def store(tmp_path: Path) -> TeamStore:
    """임시 폴더에 만든 저장소."""
    instance = TeamStore(data_dir=tmp_path / "data", project_root=tmp_path)
    instance.ensure_schema()
    return instance


@pytest.fixture
async def service(tmp_path: Path) -> AsyncIterator[TeamService]:
    """구성원 2명이 등록된 서비스."""
    store = TeamStore(data_dir=tmp_path / "data", project_root=tmp_path)
    instance = TeamService(
        store,
        log_path=tmp_path / "logs" / "team.jsonl",
        max_attachment_bytes=SMALL_LIMIT,
    )
    await instance.start()
    await instance.register_member("kim", "김태현")
    await instance.register_member("lee", "이영희")
    yield instance
    await instance.stop()


def _make_file(path: Path, size: int = 1024) -> Path:
    """지정한 크기의 임시 파일을 만든다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


# ============================================================
# 1. 순수 로직
# ============================================================


def test_classify_media_by_extension() -> None:
    """확장자로 이미지/영상/파일을 구분해야 한다."""
    assert classify_media("화면.png") == "image"
    assert classify_media("사진.JPG") == "image"
    assert classify_media("회의영상.mp4") == "video"
    assert classify_media("녹화.MOV") == "video"
    assert classify_media("보고서.docx") == "file"
    assert classify_media("이름없음") == "file"


def test_safe_filename_blocks_path_escape() -> None:
    """
    파일 이름으로 저장 위치를 벗어날 수 없어야 한다. (보안)

    상대 경로를 파일명에 넣어 엉뚱한 폴더에 쓰는 공격을 막는다.
    """
    assert safe_filename("../../../etc/passwd") == "passwd"
    assert safe_filename("..\\..\\windows\\system32\\evil.dll") == "evil.dll"
    assert safe_filename("/etc/shadow") == "shadow"
    assert "/" not in safe_filename("a/b/c.txt")
    assert "\\" not in safe_filename("a\\b\\c.txt")


def test_safe_filename_handles_empty() -> None:
    """이름이 비거나 점만 있으면 기본 이름을 쓴다."""
    assert safe_filename("") == "첨부파일"
    assert safe_filename("   ") == "첨부파일"
    assert safe_filename("..") == "첨부파일"


def test_safe_filename_keeps_korean() -> None:
    """한글 파일 이름은 그대로 살려야 한다."""
    assert safe_filename("소듐이온배터리 보고서.docx") == "소듐이온배터리 보고서.docx"


# ============================================================
# 2. 저장소
# ============================================================


def test_create_room_registers_creator(store: TeamStore) -> None:
    """방을 만들면 만든 사람이 자동으로 참여자가 되어야 한다."""
    store.upsert_member("kim", "김태현")
    room = store.create_room("주간회의", kind="meeting", created_by="kim")
    assert room.member_ids == ["kim"]
    assert room.kind == "meeting"
    assert room.is_open is True


def test_create_room_rejects_blank_name(store: TeamStore) -> None:
    """방 이름이 비면 한글 안내로 거부해야 한다."""
    with pytest.raises(TeamStoreError) as exc_info:
        store.create_room("   ", created_by="kim")
    assert "이름" in str(exc_info.value)


def test_create_room_rejects_unknown_kind(store: TeamStore) -> None:
    """알 수 없는 방 종류는 거부해야 한다."""
    with pytest.raises(TeamStoreError):
        store.create_room("방", kind="broadcast", created_by="kim")  # type: ignore[arg-type]


def test_messages_are_ordered(store: TeamStore) -> None:
    """메시지는 보낸 순서대로 조회되어야 한다."""
    room = store.create_room("대화", created_by="kim")
    for index in range(5):
        store.add_message(room.id, "kim", body=f"{index}번 메시지")

    messages = store.list_messages(room.id)
    assert [message.body for message in messages] == [
        f"{index}번 메시지" for index in range(5)
    ]


def test_after_id_returns_only_new_messages(store: TeamStore) -> None:
    """after_id 로 새 메시지만 받아올 수 있어야 한다. (실시간 갱신용)"""
    room = store.create_room("대화", created_by="kim")
    first = store.add_message(room.id, "kim", body="처음")
    store.add_message(room.id, "lee", body="다음")

    fresh = store.list_messages(room.id, after_id=first.id)
    assert [message.body for message in fresh] == ["다음"]


def test_empty_message_rejected(store: TeamStore) -> None:
    """내용도 첨부도 없으면 보낼 수 없어야 한다."""
    room = store.create_room("대화", created_by="kim")
    with pytest.raises(TeamStoreError) as exc_info:
        store.add_message(room.id, "kim", body="   ")
    assert "내용" in str(exc_info.value)


def test_unknown_room_gives_korean_error(store: TeamStore) -> None:
    """없는 방을 쓰면 한글 안내가 나와야 한다."""
    with pytest.raises(TeamStoreError) as exc_info:
        store.require_room("room_없음")
    assert "찾을 수 없습니다" in str(exc_info.value)


# ============================================================
# 3. 기록 보존 (감사 목적)
# ============================================================


def test_deleted_message_keeps_record(store: TeamStore) -> None:
    """
    삭제해도 기록은 남아야 한다. (소프트 삭제)

    화면에서는 내용이 가려지지만, 언제 누가 무엇을 지웠는지는 추적 가능해야 한다.
    """
    room = store.create_room("대화", created_by="kim")
    message = store.add_message(room.id, "kim", body="비밀 내용")

    deleted = store.delete_message(message.id, "kim")

    assert deleted.is_deleted is True
    assert deleted.deleted_at is not None
    # 화면 표시용 dict 에서는 본문이 감춰진다.
    assert deleted.to_dict()["body"] == ""
    # 그러나 행 자체는 남아 있다.
    assert store.get_message(message.id) is not None
    assert store.list_messages(room.id, include_deleted=True)


def test_cannot_delete_others_message(store: TeamStore) -> None:
    """남의 메시지는 지울 수 없어야 한다."""
    room = store.create_room("대화", created_by="kim")
    message = store.add_message(room.id, "kim", body="내 메시지")

    with pytest.raises(TeamStoreError) as exc_info:
        store.delete_message(message.id, "lee")
    assert "본인" in str(exc_info.value)


async def test_audit_log_is_append_only(service: TeamService, tmp_path: Path) -> None:
    """모든 활동이 기록 파일에 남아야 한다."""
    room = await service.create_room("감사테스트", created_by="kim")
    await service.send_text(room.id, "kim", "첫 메시지")
    message = await service.send_text(room.id, "lee", "둘째 메시지")
    await service.delete_message(message.id, "lee")

    log_path = tmp_path / "logs" / "team.jsonl"
    assert log_path.is_file(), "기록 파일이 만들어지지 않았다"

    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actions = [entry["action"] for entry in entries]

    assert "room_created" in actions
    assert "message_sent" in actions
    assert "message_deleted" in actions
    # 삭제 기록에도 누가 지웠는지 남아야 한다.
    deletion = next(entry for entry in entries if entry["action"] == "message_deleted")
    assert deletion["member_id"] == "lee"


async def test_audit_log_keeps_korean(service: TeamService, tmp_path: Path) -> None:
    """기록 파일의 한글이 깨지지 않아야 한다."""
    room = await service.create_room("한글 회의", kind="meeting", created_by="kim")
    await service.send_text(room.id, "kim", "소듐이온배터리 정책 검토")

    text = (tmp_path / "logs" / "team.jsonl").read_text(encoding="utf-8")
    assert "한글 회의" in text
    assert "소듐이온배터리" in text


# ============================================================
# 4. 파일 / 이미지 / 영상
# ============================================================


async def test_send_file_stores_inside_project(
    service: TeamService, tmp_path: Path
) -> None:
    """첨부 파일이 프로젝트 폴더 안에 저장되어야 한다. (포터블 원칙)"""
    room = await service.create_room("자료 공유", created_by="kim")
    source = _make_file(tmp_path / "보고서.docx", 2048)

    message = await service.send_file(
        room.id, "kim", filename="보고서.docx", source=source
    )

    attachment = message.attachment
    assert attachment is not None
    assert attachment.media_type == "file"
    assert attachment.size_bytes == 2048
    # 상대경로로 저장되어야 USB 이동 시 따라간다.
    assert not Path(attachment.stored_path).is_absolute()
    full = service.attachment_full_path(attachment)
    assert full.is_file()
    assert full.resolve().is_relative_to(tmp_path.resolve())


async def test_image_and_video_are_classified(
    service: TeamService, tmp_path: Path
) -> None:
    """이미지와 영상이 종류에 맞게 분류되어야 한다."""
    room = await service.create_room("자료 공유", created_by="kim")

    image = await service.send_file(
        room.id, "kim", filename="화면.png", source=_make_file(tmp_path / "a.png")
    )
    video = await service.send_file(
        room.id, "kim", filename="회의.mp4", source=_make_file(tmp_path / "b.mp4")
    )

    assert image.kind == "image"
    assert video.kind == "video"


async def test_oversized_file_rejected(service: TeamService, tmp_path: Path) -> None:
    """용량 제한을 넘는 파일은 한글 안내와 함께 거부되어야 한다."""
    room = await service.create_room("자료 공유", created_by="kim")
    big = _make_file(tmp_path / "큰영상.mp4", SMALL_LIMIT + 1)

    with pytest.raises(TeamStoreError) as exc_info:
        await service.send_file(room.id, "kim", filename="큰영상.mp4", source=big)

    message = str(exc_info.value)
    assert "너무 큽니다" in message
    assert "MB" in message


async def test_missing_file_rejected(service: TeamService, tmp_path: Path) -> None:
    """없는 파일을 보내려 하면 안내해야 한다."""
    room = await service.create_room("자료 공유", created_by="kim")
    with pytest.raises(TeamStoreError) as exc_info:
        await service.send_file(
            room.id, "kim", filename="없음.txt", source=tmp_path / "없음.txt"
        )
    assert "찾을 수 없습니다" in str(exc_info.value)


async def test_attachment_hash_recorded(service: TeamService, tmp_path: Path) -> None:
    """첨부 파일 해시가 기록되어야 한다. (기록이 바뀌지 않았음을 확인)"""
    room = await service.create_room("자료 공유", created_by="kim")
    message = await service.send_file(
        room.id, "kim", filename="자료.txt", source=_make_file(tmp_path / "자료.txt")
    )
    assert message.attachment is not None
    assert len(message.attachment.sha256) == 64


async def test_file_with_escaping_name_is_contained(
    service: TeamService, tmp_path: Path
) -> None:
    """
    파일 이름에 경로가 섞여 있어도 저장 폴더를 벗어나면 안 된다. (보안)
    """
    room = await service.create_room("자료 공유", created_by="kim")
    source = _make_file(tmp_path / "정상.txt")

    message = await service.send_file(
        room.id, "kim", filename="../../../탈출.txt", source=source
    )

    attachment = message.attachment
    assert attachment is not None
    full = service.attachment_full_path(attachment)
    assert full.resolve().is_relative_to((tmp_path / "data" / "attachments").resolve())


# ============================================================
# 5. 회의
# ============================================================


async def test_closed_meeting_blocks_messages(service: TeamService) -> None:
    """종료된 회의에는 메시지를 보낼 수 없어야 한다."""
    room = await service.create_room("주간회의", kind="meeting", created_by="kim")
    await service.send_text(room.id, "kim", "진행 중")
    await service.close_room(room.id, "kim")

    with pytest.raises(TeamStoreError) as exc_info:
        await service.send_text(room.id, "kim", "끝난 뒤")
    assert "종료" in str(exc_info.value)


async def test_closed_meeting_keeps_history(service: TeamService) -> None:
    """회의를 종료해도 기록은 그대로 남아야 한다."""
    room = await service.create_room("주간회의", kind="meeting", created_by="kim")
    await service.send_text(room.id, "kim", "논의 내용")
    await service.close_room(room.id, "kim")

    messages = await service.list_messages(room.id)
    assert any("논의 내용" == message.body for message in messages)


async def test_reopened_meeting_accepts_messages(service: TeamService) -> None:
    """다시 연 회의에는 메시지를 보낼 수 있어야 한다."""
    room = await service.create_room("주간회의", kind="meeting", created_by="kim")
    await service.close_room(room.id, "kim")
    await service.reopen_room(room.id, "kim")

    message = await service.send_text(room.id, "kim", "재개")
    assert message.body == "재개"


async def test_join_and_leave_are_recorded(service: TeamService) -> None:
    """참여/퇴장이 시스템 메시지로 남아야 한다."""
    room = await service.create_room("대화", created_by="kim")
    await service.join_room(room.id, "lee")
    await service.leave_room(room.id, "lee")

    bodies = [message.body for message in await service.list_messages(room.id)]
    assert any("이영희 님이 참여했습니다." in body for body in bodies)
    assert any("이영희 님이 나갔습니다." in body for body in bodies)


# ============================================================
# 6. 회의록
# ============================================================


async def test_transcript_includes_everything(
    service: TeamService, tmp_path: Path
) -> None:
    """회의록에 참석자·대화·첨부가 모두 담겨야 한다."""
    room = await service.create_room(
        "소듐이온배터리 대책회의", kind="meeting", created_by="kim", member_ids=["lee"]
    )
    await service.send_text(room.id, "kim", "정책 동향을 검토합니다")
    await service.send_text(room.id, "lee", "자료 공유드립니다")
    await service.send_file(
        room.id, "lee", filename="정책자료.docx", source=_make_file(tmp_path / "p.docx")
    )
    await service.close_room(room.id, "kim")

    transcript = await service.build_transcript(room.id)

    assert "소듐이온배터리 대책회의 회의록" in transcript
    assert "김태현" in transcript and "이영희" in transcript
    assert "정책 동향을 검토합니다" in transcript
    assert "[파일] 정책자료.docx" in transcript
    assert "회의가 종료되었습니다." in transcript


async def test_transcript_marks_deleted_messages(service: TeamService) -> None:
    """회의록에 삭제된 메시지도 '삭제됨'으로 표시되어야 한다. (기록 투명성)"""
    room = await service.create_room("대화", created_by="kim")
    message = await service.send_text(room.id, "kim", "지울 내용")
    await service.delete_message(message.id, "kim")

    transcript = await service.build_transcript(room.id)
    assert "(삭제된 메시지)" in transcript
    assert "지울 내용" not in transcript


# ============================================================
# 7. 실시간 전달
# ============================================================


async def test_subscriber_receives_new_message(service: TeamService) -> None:
    """접속한 구성원이 새 메시지를 즉시 받아야 한다."""
    room = await service.create_room("대화", created_by="kim")
    queue = service.subscribe(room.id)

    await service.send_text(room.id, "lee", "안녕하세요")

    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event["type"] == "message"
    assert event["message"]["body"] == "안녕하세요"
    assert event["message"]["member_id"] == "lee"

    service.unsubscribe(room.id, queue)
    assert service.subscriber_count(room.id) == 0


async def test_subscriber_only_gets_own_room(service: TeamService) -> None:
    """다른 방의 메시지는 받지 않아야 한다."""
    room_a = await service.create_room("A방", created_by="kim")
    room_b = await service.create_room("B방", created_by="kim")
    queue = service.subscribe(room_a.id)

    await service.send_text(room_b.id, "kim", "B방 메시지")

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(queue.get(), timeout=0.3)

    service.unsubscribe(room_a.id, queue)


# ============================================================
# 8. REST API
# ============================================================


@pytest.fixture
async def api_client(tmp_path: Path) -> AsyncIterator[Any]:
    """팀 API 만 올린 테스트 클라이언트. (MCP/LLM 없이 검증)"""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.team.api import create_team_router, team_context

    store = TeamStore(data_dir=tmp_path / "data", project_root=tmp_path)
    service = TeamService(
        store,
        log_path=tmp_path / "logs" / "team.jsonl",
        max_attachment_bytes=SMALL_LIMIT,
    )
    await service.start()
    await service.register_member("kim", "김태현")
    team_context.bind(service, member_id="kim", display_name="김태현")

    app = FastAPI()
    app.include_router(create_team_router())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await service.stop()


async def test_api_me(api_client: Any) -> None:
    """내 정보를 조회할 수 있어야 한다."""
    response = await api_client.get("/api/team/me")
    assert response.status_code == 200
    data = response.json()
    assert data["member_id"] == "kim"
    assert data["display_name"] == "김태현"
    assert data["enabled"] is True


async def test_api_room_lifecycle(api_client: Any) -> None:
    """방 만들기 → 메시지 → 조회 → 회의 종료가 API 로 동작해야 한다."""
    created = await api_client.post(
        "/api/team/rooms", json={"name": "API 회의", "kind": "meeting"}
    )
    assert created.status_code == 200, created.text
    room_id = created.json()["id"]

    sent = await api_client.post(
        f"/api/team/rooms/{room_id}/messages", json={"body": "안녕하세요"}
    )
    assert sent.status_code == 200, sent.text

    listed = await api_client.get(f"/api/team/rooms/{room_id}/messages")
    bodies = [item["body"] for item in listed.json()["messages"]]
    assert "안녕하세요" in bodies

    closed = await api_client.post(f"/api/team/rooms/{room_id}/close")
    assert closed.status_code == 200
    assert closed.json()["is_open"] is False

    # 종료 후에는 거부되어야 한다.
    blocked = await api_client.post(
        f"/api/team/rooms/{room_id}/messages", json={"body": "끝난 뒤"}
    )
    assert blocked.status_code == 400
    assert "종료" in blocked.json()["detail"]


async def test_api_upload_and_download(api_client: Any) -> None:
    """파일 업로드와 내려받기가 동작해야 한다."""
    created = await api_client.post("/api/team/rooms", json={"name": "자료방"})
    room_id = created.json()["id"]

    response = await api_client.post(
        f"/api/team/rooms/{room_id}/upload",
        files={"file": ("보고서.docx", b"hello-file-content", "application/octet-stream")},
        data={"body": "확인 부탁드립니다"},
    )
    assert response.status_code == 200, response.text
    message = response.json()
    assert message["kind"] == "file"
    assert message["attachment"]["filename"] == "보고서.docx"

    attachment_id = message["attachment"]["id"]
    downloaded = await api_client.get(f"/api/team/attachments/{attachment_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == b"hello-file-content"


async def test_api_upload_rejects_oversized(api_client: Any) -> None:
    """용량을 넘는 업로드는 한글 안내로 거부해야 한다."""
    created = await api_client.post("/api/team/rooms", json={"name": "자료방"})
    room_id = created.json()["id"]

    response = await api_client.post(
        f"/api/team/rooms/{room_id}/upload",
        files={"file": ("큰영상.mp4", b"x" * (SMALL_LIMIT + 1), "video/mp4")},
    )
    assert response.status_code == 400
    assert "너무 큽니다" in response.json()["detail"]


async def test_api_transcript(api_client: Any) -> None:
    """회의록을 문서 형태로 받을 수 있어야 한다."""
    created = await api_client.post(
        "/api/team/rooms", json={"name": "기록 회의", "kind": "meeting"}
    )
    room_id = created.json()["id"]
    await api_client.post(
        f"/api/team/rooms/{room_id}/messages", json={"body": "논의 시작"}
    )

    response = await api_client.get(f"/api/team/rooms/{room_id}/transcript")
    assert response.status_code == 200
    assert "기록 회의 회의록" in response.text
    assert "논의 시작" in response.text


async def test_api_unknown_room_returns_404(api_client: Any) -> None:
    """없는 방을 조회하면 404 와 한글 안내가 나와야 한다."""
    response = await api_client.get("/api/team/rooms/room_없음")
    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]


async def test_api_delete_keeps_record(api_client: Any) -> None:
    """API 로 삭제해도 기록이 남아야 한다."""
    created = await api_client.post("/api/team/rooms", json={"name": "삭제 확인"})
    room_id = created.json()["id"]
    sent = await api_client.post(
        f"/api/team/rooms/{room_id}/messages", json={"body": "지울 내용"}
    )
    message_id = sent.json()["id"]

    deleted = await api_client.delete(f"/api/team/messages/{message_id}")
    assert deleted.status_code == 200
    assert deleted.json()["is_deleted"] is True

    listed = await api_client.get(f"/api/team/rooms/{room_id}/messages")
    entry = next(
        item for item in listed.json()["messages"] if item["id"] == message_id
    )
    assert entry["is_deleted"] is True
    assert entry["body"] == ""  # 내용은 가려지고 기록만 남는다


async def test_api_stats(api_client: Any) -> None:
    """저장 현황을 확인할 수 있어야 한다."""
    await api_client.post("/api/team/rooms", json={"name": "통계"})
    response = await api_client.get("/api/team/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["rooms"] >= 1
    assert data["members"] >= 1


# ============================================================
# 9. MCP 서버 (Agent 가 도구로 공유)
# ============================================================


async def test_mcp_team_tools_registered() -> None:
    """team MCP 서버가 4개 도구를 제공해야 한다."""
    from app.mcp_servers.team_server import TeamMCPServer

    server = TeamMCPServer()
    assert set(server.tool_names()) == {
        "list_rooms",
        "post_message",
        "share_file",
        "export_transcript",
    }


async def test_mcp_share_file_blocks_outside_project() -> None:
    """
    🔴 보안: 프로젝트 폴더 밖의 파일은 공유할 수 없어야 한다.

    사용자 PC 의 아무 파일이나 팀에 유출되는 것을 막는다.
    """
    from app.mcp_servers.base_server import MCPToolError
    from app.mcp_servers.team_server import TeamMCPServer

    server = TeamMCPServer()
    with pytest.raises(MCPToolError) as exc_info:
        await server.handle_call(
            "share_file", {"room_id": "room_x", "path": "/etc/passwd"}
        )
    assert "프로젝트 폴더 밖" in str(exc_info.value)


async def test_mcp_unknown_tool_gives_korean_error() -> None:
    """없는 도구를 부르면 한글 안내가 나와야 한다."""
    from app.mcp_servers.base_server import MCPToolError
    from app.mcp_servers.team_server import TeamMCPServer

    server = TeamMCPServer()
    with pytest.raises(MCPToolError) as exc_info:
        await server.handle_call("없는도구", {})
    assert "team 서버에" in str(exc_info.value)


async def test_agent_can_post_and_share(tmp_path: Path, monkeypatch: Any) -> None:
    """
    Agent 가 MCP 도구로 대화방에 글을 남기고 파일을 공유할 수 있어야 한다.

    보고서를 만든 뒤 팀에 바로 전달하는 실제 흐름을 재현한다.
    """
    import dataclasses

    from app.config import settings as settings_module
    from app.mcp_servers import team_server as team_module

    # 저장 위치를 임시 폴더로 돌린다.
    fake = dataclasses.replace(
        settings_module.load_settings(),
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        project_root=tmp_path,
    )
    monkeypatch.setattr(team_module, "get_settings", lambda: fake)

    def fake_safe_path(path: str, *, must_exist: bool = False) -> Path:
        """임시 폴더를 프로젝트 루트로 삼아 경로를 해석한다."""
        candidate = Path(path)
        resolved = (
            candidate if candidate.is_absolute() else (tmp_path / candidate)
        ).resolve()
        # 실제 구현과 동일하게 루트 밖 경로는 막는다.
        if not resolved.is_relative_to(tmp_path.resolve()):
            from app.mcp_servers.base_server import MCPToolError

            raise MCPToolError(f"보안 정책상 프로젝트 폴더 밖의 경로는 쓸 수 없습니다: {path}")
        if must_exist and not resolved.exists():
            from app.mcp_servers.base_server import MCPToolError

            raise MCPToolError(f"파일 또는 폴더를 찾을 수 없습니다: {path}")
        return resolved

    monkeypatch.setattr(team_module, "safe_project_path", fake_safe_path)

    server = team_module.TeamMCPServer()

    # 사람이 먼저 방을 만든다.
    service = await server._get_service()
    room = await service.create_room("보고 채널", created_by="kim")

    # Agent 가 글을 남긴다.
    posted = await server.handle_call(
        "post_message", {"room_id": room.id, "body": "보고서 초안을 올립니다."}
    )
    assert posted["room_id"] == room.id

    # Agent 가 파일을 공유한다.
    report = _make_file(tmp_path / "보고서.docx", 512)
    shared = await server.handle_call(
        "share_file",
        {"room_id": room.id, "path": str(report), "message": "검토 부탁드립니다"},
    )
    assert shared["filename"] == "보고서.docx"
    assert shared["media_type"] == "file"

    # 대화방 목록에도 보인다.
    listed = await server.handle_call("list_rooms", {})
    assert listed["count"] >= 1

    # 회의록을 저장한다.
    exported = await server.handle_call("export_transcript", {"room_id": room.id})
    transcript_path = tmp_path / exported["path"]
    assert transcript_path.is_file()
    text = transcript_path.read_text(encoding="utf-8")
    assert "보고서 초안을 올립니다." in text
    assert "PFM-Agent" in text

    await service.stop()
