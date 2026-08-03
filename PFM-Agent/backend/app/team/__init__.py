"""
팀 협업 모듈 — 같은 그룹 구성원끼리 대화·회의·파일 공유.

구성
----
  - `store.py`   : SQLite 저장소 (대화·회의·첨부파일)
  - `service.py` : 비동기 서비스 + 실시간 전달 + 기록

폐쇄망 연결 방식
----------------
한 PC 가 **호스트**가 되어 백엔드를 열고, 같은 사내망의 다른 PC 들이
그 주소로 접속한다. 별도 서버 인프라가 필요 없다.
(`.env` 의 `TEAM_SERVER_ENABLED` / `BACKEND_HOST` 참고)
"""

from app.team.service import TeamService
from app.team.store import (
    Attachment,
    Member,
    Message,
    Room,
    TeamStore,
    TeamStoreError,
)

__all__ = [
    "Attachment",
    "Member",
    "Message",
    "Room",
    "TeamService",
    "TeamStore",
    "TeamStoreError",
]
