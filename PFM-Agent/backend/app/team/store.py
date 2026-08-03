"""
팀 협업(대화·회의·파일) 저장소.

같은 그룹 구성원끼리 대화하고, 파일·이미지·영상을 주고받은 내역을
**모두 기록**하는 저장 계층이다.

저장 위치 (포터블 원칙 — 전부 프로젝트 폴더 내부)
--------------------------------------------------
  - 대화 기록 : `./data/team.db`        (SQLite)
  - 첨부 파일 : `./data/attachments/`   (원본 파일)

왜 SQLite 인가
--------------
  - 별도 서버 프로세스가 필요 없다. (폐쇄망/USB 배포에 적합)
  - 트랜잭션이 보장되어 기록이 중간에 깨지지 않는다.
  - 파일 하나라 USB 로 폴더째 옮기면 대화 기록도 함께 따라간다.

기록 보존 원칙
--------------
메시지는 **완전히 지우지 않는다.** 삭제 요청이 와도 `deleted_at` 만 채우는
소프트 삭제로 처리해, "무슨 일이 있었는지" 추적할 수 있게 한다.
(회의록·감사 목적)
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

#: 방 종류
RoomKind = Literal["chat", "meeting"]

#: 메시지 종류
MessageKind = Literal["text", "file", "image", "video", "system"]

#: 첨부 파일 분류
MediaType = Literal["image", "video", "file"]

#: 이미지로 취급할 확장자
IMAGE_SUFFIXES: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}
)

#: 영상으로 취급할 확장자
VIDEO_SUFFIXES: frozenset[str] = frozenset(
    {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}
)

#: 한 번에 가져올 메시지 기본 개수
DEFAULT_PAGE_SIZE: int = 100

#: 한 번에 가져올 메시지 최대 개수
MAX_PAGE_SIZE: int = 500

_SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    closed_at  TEXT
);

CREATE TABLE IF NOT EXISTS room_members (
    room_id   TEXT NOT NULL,
    member_id TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (room_id, member_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id            TEXT PRIMARY KEY,
    room_id       TEXT NOT NULL,
    member_id     TEXT NOT NULL,
    filename      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,
    media_type    TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id       TEXT NOT NULL,
    member_id     TEXT NOT NULL,
    kind          TEXT NOT NULL,
    body          TEXT NOT NULL DEFAULT '',
    attachment_id TEXT,
    created_at    TEXT NOT NULL,
    edited_at     TEXT,
    deleted_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_room
    ON messages (room_id, id);
CREATE INDEX IF NOT EXISTS idx_attachments_room
    ON attachments (room_id);
"""


class TeamStoreError(RuntimeError):
    """팀 저장소 오류. 메시지는 사용자에게 그대로 보이므로 한글로 작성한다."""


def _now() -> str:
    """ISO 8601 UTC 타임스탬프."""
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    """짧고 읽기 쉬운 식별자를 만든다. (예: room_3f2a1b8c)"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def classify_media(filename: str) -> MediaType:
    """
    파일 이름으로 종류를 판단한다.

    이미지/영상은 화면에서 바로 보여주고, 나머지는 첨부파일로 처리한다.
    """
    suffix = Path(filename).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    return "file"


def safe_filename(raw: str) -> str:
    """
    업로드된 파일 이름을 안전하게 만든다.

    경로 구분자와 상위 폴더 표기를 제거해 **저장 위치를 벗어나지 못하게** 한다.
    (`../../etc/passwd` 같은 이름으로 파일이 엉뚱한 곳에 저장되는 것을 막는다)
    """
    name = Path(str(raw).replace("\\", "/")).name.strip()
    # 앞뒤 점과 공백을 정리한다. (".." / "." 만 남는 경우 방지)
    name = name.strip(". ")
    if not name:
        return "첨부파일"
    return name[:150]


def file_sha256(path: Path) -> str:
    """파일 무결성 확인용 해시. (기록이 바뀌지 않았음을 확인)"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Member:
    """구성원 한 명."""

    id: str
    display_name: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """API 응답용 dict."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Room:
    """대화방 또는 회의방."""

    id: str
    name: str
    kind: RoomKind
    created_by: str
    created_at: str
    closed_at: str | None = None
    member_ids: list[str] = field(default_factory=list)
    message_count: int = 0
    last_message_at: str | None = None

    @property
    def is_open(self) -> bool:
        """아직 진행 중인지. (회의는 종료할 수 있다)"""
        return self.closed_at is None

    def to_dict(self) -> dict[str, Any]:
        """API 응답용 dict."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "closed_at": self.closed_at,
            "is_open": self.is_open,
            "member_ids": list(self.member_ids),
            "message_count": self.message_count,
            "last_message_at": self.last_message_at,
        }


@dataclass(frozen=True)
class Attachment:
    """주고받은 파일 한 건."""

    id: str
    room_id: str
    member_id: str
    filename: str
    stored_path: str
    """프로젝트 루트 기준 상대경로 (포터블 원칙)"""

    media_type: MediaType
    size_bytes: int
    sha256: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """API 응답용 dict."""
        return {
            "id": self.id,
            "room_id": self.room_id,
            "member_id": self.member_id,
            "filename": self.filename,
            "stored_path": self.stored_path,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class Message:
    """대화 메시지 한 건."""

    id: int
    room_id: str
    member_id: str
    kind: MessageKind
    body: str
    created_at: str
    attachment: Attachment | None = None
    edited_at: str | None = None
    deleted_at: str | None = None

    @property
    def is_deleted(self) -> bool:
        """삭제 표시된 메시지인지. (기록은 남아 있다)"""
        return self.deleted_at is not None

    def to_dict(self) -> dict[str, Any]:
        """API 응답용 dict."""
        return {
            "id": self.id,
            "room_id": self.room_id,
            "member_id": self.member_id,
            "kind": self.kind,
            # 삭제된 메시지는 본문을 감추되 '삭제됨' 사실은 남긴다.
            "body": "" if self.is_deleted else self.body,
            "created_at": self.created_at,
            "edited_at": self.edited_at,
            "deleted_at": self.deleted_at,
            "is_deleted": self.is_deleted,
            "attachment": None if self.is_deleted or self.attachment is None
            else self.attachment.to_dict(),
        }


class TeamStore:
    """
    팀 대화·회의·파일 저장소. (SQLite)

    ⚠️ 이 클래스의 메서드는 **동기**다. 이벤트 루프를 막지 않도록
    서비스 계층에서 `asyncio.to_thread` 로 호출한다.

    Example:
        store = TeamStore(data_dir=settings.data_dir)
        store.ensure_schema()
        room = store.create_room("주간회의", kind="meeting", created_by=me.id)
    """

    def __init__(self, data_dir: Path, *, project_root: Path | None = None) -> None:
        """
        Args:
            data_dir: 데이터 폴더 (프로젝트 내부)
            project_root: 상대경로 계산 기준. 생략 시 data_dir 의 부모
        """
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root) if project_root else self.data_dir.parent
        self.db_path = self.data_dir / "team.db"
        self.attachment_dir = self.data_dir / "attachments"
        self._connection: sqlite3.Connection | None = None

    # ------------------------------------------------------------
    # 연결 / 스키마
    # ------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        """DB 연결을 만든다. (한 번 만들어 재사용)"""
        if self._connection is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                self.db_path, check_same_thread=False, timeout=10.0
            )
            connection.row_factory = sqlite3.Row
            # 여러 PC 가 붙어 동시에 쓰므로 WAL 로 읽기/쓰기 충돌을 줄인다.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._connection = connection
        return self._connection

    def ensure_schema(self) -> None:
        """테이블을 만든다. (이미 있으면 아무 일도 하지 않는다)"""
        connection = self.connect()
        with connection:
            connection.executescript(_SCHEMA)
        self.attachment_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        """연결을 닫는다."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    # ------------------------------------------------------------
    # 구성원
    # ------------------------------------------------------------
    def upsert_member(self, member_id: str, display_name: str) -> Member:
        """
        구성원을 등록하거나 이름을 갱신한다.

        Raises:
            TeamStoreError: 이름이 비어 있는 경우
        """
        name = display_name.strip()
        if not name:
            raise TeamStoreError("표시할 이름을 입력하세요.")

        connection = self.connect()
        now = _now()
        with connection:
            connection.execute(
                """
                INSERT INTO members (id, display_name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET display_name = excluded.display_name
                """,
                (member_id, name, now),
            )
        row = connection.execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        ).fetchone()
        return Member(
            id=row["id"],
            display_name=row["display_name"],
            created_at=row["created_at"],
        )

    def get_member(self, member_id: str) -> Member | None:
        """구성원 한 명을 조회한다."""
        row = self.connect().execute(
            "SELECT * FROM members WHERE id = ?", (member_id,)
        ).fetchone()
        if row is None:
            return None
        return Member(
            id=row["id"],
            display_name=row["display_name"],
            created_at=row["created_at"],
        )

    def list_members(self) -> list[Member]:
        """등록된 구성원 전체."""
        rows = self.connect().execute(
            "SELECT * FROM members ORDER BY display_name"
        ).fetchall()
        return [
            Member(
                id=row["id"],
                display_name=row["display_name"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # ------------------------------------------------------------
    # 방 (대화 / 회의)
    # ------------------------------------------------------------
    def create_room(
        self,
        name: str,
        *,
        kind: RoomKind = "chat",
        created_by: str,
        member_ids: list[str] | None = None,
    ) -> Room:
        """
        대화방 또는 회의방을 만든다.

        Raises:
            TeamStoreError: 이름이 비어 있거나 종류가 잘못된 경우
        """
        room_name = name.strip()
        if not room_name:
            raise TeamStoreError("방 이름을 입력하세요.")
        if kind not in ("chat", "meeting"):
            raise TeamStoreError(
                f"알 수 없는 방 종류입니다: {kind} (chat 또는 meeting 만 가능)"
            )

        room_id = new_id("room")
        now = _now()
        members = list(dict.fromkeys([created_by, *(member_ids or [])]))

        connection = self.connect()
        with connection:
            connection.execute(
                """
                INSERT INTO rooms (id, name, kind, created_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (room_id, room_name, kind, created_by, now),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO room_members (room_id, member_id, joined_at)"
                " VALUES (?, ?, ?)",
                [(room_id, member, now) for member in members],
            )

        room = self.get_room(room_id)
        assert room is not None  # 방금 만들었으므로 반드시 존재한다.
        return room

    def get_room(self, room_id: str) -> Room | None:
        """방 하나를 조회한다. (구성원·메시지 수 포함)"""
        connection = self.connect()
        row = connection.execute(
            "SELECT * FROM rooms WHERE id = ?", (room_id,)
        ).fetchone()
        if row is None:
            return None

        member_ids = [
            item["member_id"]
            for item in connection.execute(
                "SELECT member_id FROM room_members WHERE room_id = ? ORDER BY joined_at",
                (room_id,),
            ).fetchall()
        ]
        stats = connection.execute(
            "SELECT COUNT(*) AS count, MAX(created_at) AS last FROM messages"
            " WHERE room_id = ? AND deleted_at IS NULL",
            (room_id,),
        ).fetchone()

        return Room(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            closed_at=row["closed_at"],
            member_ids=member_ids,
            message_count=stats["count"] or 0,
            last_message_at=stats["last"],
        )

    def require_room(self, room_id: str) -> Room:
        """
        방을 조회하고, 없으면 한글 오류를 낸다.

        Raises:
            TeamStoreError: 방이 없는 경우
        """
        room = self.get_room(room_id)
        if room is None:
            raise TeamStoreError(
                f"'{room_id}' 대화방을 찾을 수 없습니다. 목록에서 다시 선택해 주세요."
            )
        return room

    def list_rooms(self, *, member_id: str | None = None) -> list[Room]:
        """
        방 목록을 반환한다. (최근 활동 순)

        Args:
            member_id: 지정하면 해당 구성원이 속한 방만 반환
        """
        connection = self.connect()
        if member_id is None:
            rows = connection.execute("SELECT id FROM rooms").fetchall()
        else:
            rows = connection.execute(
                "SELECT r.id FROM rooms r"
                " JOIN room_members m ON m.room_id = r.id"
                " WHERE m.member_id = ?",
                (member_id,),
            ).fetchall()

        rooms = [room for row in rows if (room := self.get_room(row["id"])) is not None]
        # 최근 대화가 있었던 방을 위로 올린다.
        rooms.sort(key=lambda item: item.last_message_at or item.created_at, reverse=True)
        return rooms

    def join_room(self, room_id: str, member_id: str) -> Room:
        """구성원을 방에 추가한다. (이미 있으면 아무 일도 하지 않는다)"""
        self.require_room(room_id)
        connection = self.connect()
        with connection:
            connection.execute(
                "INSERT OR IGNORE INTO room_members (room_id, member_id, joined_at)"
                " VALUES (?, ?, ?)",
                (room_id, member_id, _now()),
            )
        return self.require_room(room_id)

    def leave_room(self, room_id: str, member_id: str) -> Room:
        """구성원을 방에서 제외한다. (대화 기록은 그대로 남는다)"""
        self.require_room(room_id)
        connection = self.connect()
        with connection:
            connection.execute(
                "DELETE FROM room_members WHERE room_id = ? AND member_id = ?",
                (room_id, member_id),
            )
        return self.require_room(room_id)

    def close_room(self, room_id: str) -> Room:
        """
        회의를 종료한다. (대화 기록은 그대로 보존)

        종료된 방에는 더 이상 메시지를 보낼 수 없다.
        """
        room = self.require_room(room_id)
        if not room.is_open:
            return room

        connection = self.connect()
        with connection:
            connection.execute(
                "UPDATE rooms SET closed_at = ? WHERE id = ?", (_now(), room_id)
            )
        return self.require_room(room_id)

    def reopen_room(self, room_id: str) -> Room:
        """종료한 회의를 다시 연다."""
        self.require_room(room_id)
        connection = self.connect()
        with connection:
            connection.execute(
                "UPDATE rooms SET closed_at = NULL WHERE id = ?", (room_id,)
            )
        return self.require_room(room_id)

    # ------------------------------------------------------------
    # 첨부 파일
    # ------------------------------------------------------------
    def store_attachment(
        self,
        room_id: str,
        member_id: str,
        *,
        filename: str,
        source: Path,
        max_bytes: int,
        move: bool = False,
    ) -> Attachment:
        """
        파일을 저장소에 보관한다. (프로젝트 폴더 내부)

        Args:
            filename: 사용자에게 보여줄 원래 이름
            source: 원본 파일 경로
            max_bytes: 허용 최대 크기
            move: True 면 원본을 옮기고, False 면 복사한다.

        Raises:
            TeamStoreError: 파일이 없거나 크기 제한을 넘는 경우
        """
        self.require_room(room_id)

        origin = Path(source)
        if not origin.is_file():
            raise TeamStoreError(f"보낼 파일을 찾을 수 없습니다: {source}")

        size = origin.stat().st_size
        if size > max_bytes:
            raise TeamStoreError(
                f"파일이 너무 큽니다. ({size / 1024 / 1024:.1f}MB) "
                f"최대 {max_bytes / 1024 / 1024:.0f}MB 까지 보낼 수 있습니다."
            )

        clean_name = safe_filename(filename)
        attachment_id = new_id("file")
        # 방별로 폴더를 나눠 파일이 뒤섞이지 않게 한다.
        target_dir = self.attachment_dir / room_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{attachment_id}_{clean_name}"

        if move:
            shutil.move(str(origin), target)
        else:
            shutil.copy2(origin, target)

        attachment = Attachment(
            id=attachment_id,
            room_id=room_id,
            member_id=member_id,
            filename=clean_name,
            stored_path=target.resolve()
            .relative_to(self.project_root.resolve())
            .as_posix(),
            media_type=classify_media(clean_name),
            size_bytes=size,
            sha256=file_sha256(target),
            created_at=_now(),
        )

        connection = self.connect()
        with connection:
            connection.execute(
                """
                INSERT INTO attachments
                    (id, room_id, member_id, filename, stored_path,
                     media_type, size_bytes, sha256, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment.id,
                    attachment.room_id,
                    attachment.member_id,
                    attachment.filename,
                    attachment.stored_path,
                    attachment.media_type,
                    attachment.size_bytes,
                    attachment.sha256,
                    attachment.created_at,
                ),
            )
        return attachment

    def get_attachment(self, attachment_id: str) -> Attachment | None:
        """첨부 파일 정보를 조회한다."""
        row = self.connect().execute(
            "SELECT * FROM attachments WHERE id = ?", (attachment_id,)
        ).fetchone()
        return None if row is None else self._row_to_attachment(row)

    def list_attachments(self, room_id: str) -> list[Attachment]:
        """방에서 주고받은 파일 목록. (최신 순)"""
        rows = self.connect().execute(
            "SELECT * FROM attachments WHERE room_id = ? ORDER BY created_at DESC",
            (room_id,),
        ).fetchall()
        return [self._row_to_attachment(row) for row in rows]

    @staticmethod
    def _row_to_attachment(row: sqlite3.Row) -> Attachment:
        """DB 행을 Attachment 로 변환한다."""
        return Attachment(
            id=row["id"],
            room_id=row["room_id"],
            member_id=row["member_id"],
            filename=row["filename"],
            stored_path=row["stored_path"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------
    # 메시지
    # ------------------------------------------------------------
    def add_message(
        self,
        room_id: str,
        member_id: str,
        *,
        body: str = "",
        kind: MessageKind = "text",
        attachment: Attachment | None = None,
    ) -> Message:
        """
        메시지를 기록한다.

        Raises:
            TeamStoreError: 방이 없거나 종료되었거나, 내용이 비어 있는 경우
        """
        room = self.require_room(room_id)
        if not room.is_open and kind != "system":
            raise TeamStoreError(
                f"'{room.name}' 회의는 종료되어 더 이상 메시지를 보낼 수 없습니다."
            )

        text = body.strip()
        if not text and attachment is None:
            raise TeamStoreError("보낼 내용을 입력하거나 파일을 첨부하세요.")

        # 첨부가 있으면 종류를 파일 유형에 맞춘다.
        resolved_kind: MessageKind = kind
        if attachment is not None and kind == "text":
            resolved_kind = attachment.media_type

        now = _now()
        connection = self.connect()
        with connection:
            cursor = connection.execute(
                """
                INSERT INTO messages
                    (room_id, member_id, kind, body, attachment_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    room_id,
                    member_id,
                    resolved_kind,
                    text,
                    attachment.id if attachment else None,
                    now,
                ),
            )
            message_id = int(cursor.lastrowid or 0)

        return Message(
            id=message_id,
            room_id=room_id,
            member_id=member_id,
            kind=resolved_kind,
            body=text,
            created_at=now,
            attachment=attachment,
        )

    def list_messages(
        self,
        room_id: str,
        *,
        after_id: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        include_deleted: bool = True,
    ) -> list[Message]:
        """
        방의 메시지를 오래된 순으로 반환한다.

        Args:
            after_id: 이 번호보다 큰 메시지만 (실시간 갱신용)
            limit: 최대 개수
            include_deleted: 삭제된 메시지도 포함할지 (기록 확인용)
        """
        count = max(1, min(MAX_PAGE_SIZE, limit))
        query = "SELECT * FROM messages WHERE room_id = ? AND id > ?"
        if not include_deleted:
            query += " AND deleted_at IS NULL"
        query += " ORDER BY id LIMIT ?"

        rows = self.connect().execute(query, (room_id, after_id, count)).fetchall()
        return [self._row_to_message(row) for row in rows]

    def get_message(self, message_id: int) -> Message | None:
        """메시지 한 건을 조회한다."""
        row = self.connect().execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        return None if row is None else self._row_to_message(row)

    def delete_message(self, message_id: int, member_id: str) -> Message:
        """
        메시지를 삭제 표시한다. (기록은 남는다 — 소프트 삭제)

        Raises:
            TeamStoreError: 메시지가 없거나 본인 메시지가 아닌 경우
        """
        message = self.get_message(message_id)
        if message is None:
            raise TeamStoreError(f"{message_id}번 메시지를 찾을 수 없습니다.")
        if message.member_id != member_id:
            raise TeamStoreError("본인이 보낸 메시지만 삭제할 수 있습니다.")
        if message.is_deleted:
            return message

        connection = self.connect()
        with connection:
            connection.execute(
                "UPDATE messages SET deleted_at = ? WHERE id = ?", (_now(), message_id)
            )
        updated = self.get_message(message_id)
        assert updated is not None
        return updated

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        """DB 행을 Message 로 변환한다. (첨부 정보 포함)"""
        attachment = (
            self.get_attachment(row["attachment_id"]) if row["attachment_id"] else None
        )
        return Message(
            id=row["id"],
            room_id=row["room_id"],
            member_id=row["member_id"],
            kind=row["kind"],
            body=row["body"],
            created_at=row["created_at"],
            attachment=attachment,
            edited_at=row["edited_at"],
            deleted_at=row["deleted_at"],
        )

    # ------------------------------------------------------------
    # 통계
    # ------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        """저장 현황 요약. (상태 화면 표시용)"""
        connection = self.connect()

        def count(table: str) -> int:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

        total_bytes = connection.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM attachments"
        ).fetchone()[0]

        return {
            "members": count("members"),
            "rooms": count("rooms"),
            "messages": count("messages"),
            "attachments": count("attachments"),
            "attachment_bytes": int(total_bytes),
        }
