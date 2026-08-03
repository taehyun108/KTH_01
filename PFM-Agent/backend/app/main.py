"""
PFM-Agent 백엔드 진입점 (FastAPI + WebSocket).

기동 순서
---------
1. `.env` 설정 로드 및 런타임 폴더 생성 (data/logs/output)
2. 내부 MCP 서버 기동 → 도구 수집
3. LLM 클라이언트 생성 (LLM_PROVIDER 에 따라 자동 선택)
4. Agent 런타임 + 실행 관리자 준비

API
---
  POST /api/agent/run       실행 시작
  POST /api/agent/approve   위험 도구 승인/거절
  POST /api/agent/kill      실행 중단 (Kill Switch)
  GET  /api/agent/runs      실행 목록
  GET  /api/agent/run/{id}  실행 상태 조회
  GET  /api/status          서버/도구 상태
  WS   /ws/agent/{run_id}   실시간 진행 상황 (MCP 도구 로그 포함)

실행:
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8756
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agents.run_manager import RunManager
from app.agents.runtime import AgentRuntime
from app.config.settings import Settings, get_settings
from app.llm.base import LLMError
from app.mcp_client.client import MCPClient
from app.team.api import create_team_router, create_team_websocket_route, team_context
from app.team.service import TeamService
from app.team.store import TeamStore
from app.safety.kill_switch import KillSwitch
from app.safety.undo_manager import UndoError

logger = logging.getLogger("pfm-agent.main")

#: WebSocket 이벤트 대기 간격(초) — 연결 유지 확인용
WS_POLL_INTERVAL = 30.0


# ============================================================
# 요청/응답 모델
# ============================================================


class RunRequest(BaseModel):
    """실행 시작 요청."""

    message: str = Field(..., min_length=1, description="사용자 자연어 요청")


class ApproveRequest(BaseModel):
    """승인 응답 요청."""

    approval_id: str = Field(..., description="승인 요청 식별자")
    approved: bool = Field(..., description="승인하면 true, 거절하면 false")


class UndoRequest(BaseModel):
    """되돌리기 요청."""

    run_id: str | None = Field(default=None, description="기록에 남길 실행 ID")


class KillRequest(BaseModel):
    """실행 중단 요청. run_id 를 생략하면 모든 실행을 중단한다."""

    run_id: str | None = Field(default=None, description="중단할 실행 ID")


# ============================================================
# 애플리케이션 상태
# ============================================================


class AppState:
    """앱 전역에서 공유하는 객체들."""

    mcp_client: MCPClient | None = None
    runtime: AgentRuntime | None = None
    run_manager: RunManager | None = None
    kill_switch: KillSwitch | None = None
    team_service: TeamService | None = None
    startup_error: str = ""


app_state = AppState()


def get_run_manager() -> RunManager:
    """실행 관리자를 반환한다. 준비되지 않았으면 503."""
    if app_state.run_manager is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "백엔드가 아직 준비되지 않았습니다. "
                f"{app_state.startup_error or '잠시 후 다시 시도하세요.'}"
            ),
        )
    return app_state.run_manager


# ============================================================
# 생명주기
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    서버 기동/종료 시 자원을 관리한다.

    ⚠️ MCP 클라이언트의 연결/해제는 각 서버 전용 task 가 담당하므로
       lifespan 의 진입/종료 task 가 달라도 안전하다. (STEP 3 설계)
    """
    settings = get_settings()
    settings.ensure_runtime_dirs()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
    )
    logger.info("PFM-Agent 백엔드를 시작합니다 (LLM_PROVIDER=%s)", settings.llm_provider)

    # --- MCP 서버 기동 ---
    mcp_client = MCPClient.from_config()
    try:
        await mcp_client.connect()
        app_state.mcp_client = mcp_client

        if mcp_client.failed_servers:
            logger.warning(
                "일부 MCP 서버가 시작되지 않았습니다: %s", mcp_client.failed_servers
            )

        # --- 팀 협업 준비 (대화 / 회의 / 파일 공유) ---
        #     LLM 이나 MCP 가 실패해도 팀 기능은 독립적으로 동작해야 한다.
        await _start_team_service(settings)

        # --- LLM + 런타임 준비 ---
        try:
            runtime = AgentRuntime.create(mcp_client, settings=settings)
            app_state.runtime = runtime
            run_manager = RunManager(runtime)
            app_state.run_manager = run_manager

            # --- 전역 Kill Switch (ESC) 등록 ---
            # 등록에 실패해도 앱은 정상 기동한다. (화면의 정지 버튼으로 대체)
            kill_switch = KillSwitch(
                key=settings.kill_switch_key,
                on_trigger=run_manager.kill_all,
            )
            kill_switch.start()
            app_state.kill_switch = kill_switch
            if kill_switch.available:
                logger.info("비상 정지 단축키 준비 완료: %s", settings.kill_switch_key.upper())
            else:
                logger.warning("전역 단축키 사용 불가: %s", kill_switch.unavailable_reason)

            logger.info(
                "준비 완료: MCP 도구 %d개 / LLM %s",
                mcp_client.total_tool_count(),
                runtime.llm.provider,
            )
        except LLMError as exc:
            # LLM 설정이 잘못돼도 서버는 뜨게 하고, 요청 시 안내한다.
            app_state.startup_error = exc.message
            logger.error("LLM 준비 실패: %s", exc.message)

        yield

    finally:
        logger.info("PFM-Agent 백엔드를 종료합니다")
        if app_state.kill_switch is not None:
            app_state.kill_switch.stop()
            app_state.kill_switch = None
        if app_state.run_manager is not None:
            await app_state.run_manager.shutdown()
        if app_state.team_service is not None:
            await app_state.team_service.stop()
            app_state.team_service = None
        await mcp_client.aclose()
        app_state.mcp_client = None
        app_state.runtime = None
        app_state.run_manager = None


async def _start_team_service(settings: Settings) -> None:
    """
    팀 협업 저장소를 준비한다.

    실패해도 앱 전체를 멈추지 않는다. 사유를 남겨 두면 화면에서
    "왜 안 되는지"를 한글로 안내한다.
    """
    if not settings.team_enabled:
        team_context.disable(
            "팀 협업 기능이 꺼져 있습니다. (.env 의 TEAM_ENABLED=true 로 켤 수 있습니다)"
        )
        logger.info("팀 협업 기능이 꺼져 있습니다.")
        return

    try:
        store = TeamStore(data_dir=settings.data_dir, project_root=settings.project_root)
        service = TeamService(
            store,
            log_path=settings.log_dir / "team.jsonl",
            max_attachment_bytes=settings.team_max_attachment_mb * 1024 * 1024,
        )
        await service.start()

        member_id = settings.team_member_id
        display_name = settings.team_display_name or member_id
        await service.register_member(member_id, display_name)

        app_state.team_service = service
        team_context.bind(service, member_id=member_id, display_name=display_name)

        scope = "사내망 전체" if settings.team_server_enabled else "이 PC 만"
        logger.info(
            "팀 협업 준비 완료: %s (%s) / 공개 범위 %s",
            display_name,
            member_id,
            scope,
        )
    except Exception as exc:  # noqa: BLE001 - 팀 기능 실패로 앱을 멈추지 않는다
        team_context.disable(f"팀 협업 기능을 준비하지 못했습니다: {exc}")
        logger.error("팀 협업 준비 실패: %s", exc)


def create_app() -> FastAPI:
    """FastAPI 앱을 만든다. (테스트에서도 사용)"""
    settings = get_settings()

    application = FastAPI(
        title="PFM-Agent Backend",
        description="GUI 기반 AI Agent 백엔드 (FastAPI + LangGraph + 자체 MCP 서버)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 프론트엔드(Tauri/Vite)에서의 접근 허용 — 로컬 전용
    application.add_middleware(
        CORSMiddleware,
        # 팀 모드에서는 사내망의 다른 PC 화면에서도 접속하므로 출처를 넓힌다.
        # (혼자 쓸 때는 로컬 출처만 허용 — 기본값이 더 안전하다)
        allow_origins=["*"] if settings.team_server_enabled else [
            f"http://localhost:{settings.frontend_port}",
            f"http://127.0.0.1:{settings.frontend_port}",
            "tauri://localhost",
            "http://tauri.localhost",
        ],
        # 출처가 "*" 일 때 자격증명 허용은 브라우저가 거부하므로 함께 조정한다.
        allow_credentials=not settings.team_server_enabled,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_routes(application)

    # 팀 협업 (대화 / 회의 / 파일 공유)
    application.include_router(create_team_router())
    create_team_websocket_route(application)

    return application


# ============================================================
# 라우트
# ============================================================


def _register_routes(application: FastAPI) -> None:
    """API 라우트를 등록한다."""

    @application.get("/")
    async def root() -> dict[str, Any]:
        """서버 기본 정보."""
        return {
            "name": "PFM-Agent Backend",
            "version": "0.1.0",
            "docs": "/docs",
            "ready": app_state.run_manager is not None,
        }

    @application.get("/api/status")
    async def status() -> dict[str, Any]:
        """서버/도구 상태를 반환한다. (프론트엔드 초기 표시용)"""
        settings = get_settings()
        client = app_state.mcp_client
        runtime = app_state.runtime

        tools: list[dict[str, Any]] = []
        if runtime is not None:
            tools = [
                {
                    "name": tool.display_name,
                    "server": tool.server,
                    "require_approval": tool.require_approval,
                    "description": tool.description,
                }
                for tool in runtime.registry.tools
            ]

        kill_switch = app_state.kill_switch
        return {
            "ready": app_state.run_manager is not None,
            "startup_error": app_state.startup_error,
            "llm_provider": settings.llm_provider,
            "llm_model": runtime.llm.model if runtime else "",
            "require_approval": settings.require_approval,
            "kill_switch_key": settings.kill_switch_key,
            "kill_switch": (
                kill_switch.status()
                if kill_switch
                else {
                    "key": settings.kill_switch_key,
                    "global_hook_available": False,
                    "reason": "전역 단축키가 등록되지 않았습니다. 화면의 정지 버튼을 사용하세요.",
                    "trigger_count": 0,
                }
            ),
            "can_undo": runtime.undo_manager.can_undo if runtime else False,
            "undo_stack": runtime.undo_manager.list_actions() if runtime else [],
            "mcp_servers": client.connected_servers if client else [],
            "mcp_failed": client.failed_servers if client else {},
            "tools": tools,
        }

    @application.post("/api/agent/run")
    async def start_run(request: RunRequest) -> dict[str, Any]:
        """실행을 시작하고 run_id 를 반환한다."""
        manager = get_run_manager()
        record = manager.start(request.message)
        return {"run_id": record.run_id, "status": record.status}

    @application.get("/api/agent/runs")
    async def list_runs() -> dict[str, Any]:
        """실행 목록을 반환한다."""
        manager = get_run_manager()
        return {"runs": [record.to_dict() for record in manager.list_runs()]}

    @application.get("/api/agent/run/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        """실행 상태를 조회한다."""
        manager = get_run_manager()
        record = manager.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"실행을 찾을 수 없습니다: {run_id}")
        return record.to_dict()

    @application.post("/api/agent/approve")
    async def approve(request: ApproveRequest) -> dict[str, Any]:
        """위험 도구 실행을 승인하거나 거절한다."""
        manager = get_run_manager()
        handled = manager.approve(request.approval_id, request.approved)
        if not handled:
            raise HTTPException(
                status_code=404,
                detail=(
                    "이미 처리되었거나 존재하지 않는 승인 요청입니다: "
                    f"{request.approval_id}"
                ),
            )
        return {"approval_id": request.approval_id, "approved": request.approved}

    @application.post("/api/agent/kill")
    async def kill(request: KillRequest) -> dict[str, Any]:
        """
        실행을 중단한다. (Kill Switch)

        run_id 를 주면 해당 실행만, 생략하면 진행 중인 모든 실행을 중단한다.
        """
        manager = get_run_manager()

        if request.run_id:
            if not manager.kill(request.run_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"실행을 찾을 수 없습니다: {request.run_id}",
                )
            return {"killed": [request.run_id]}

        count = manager.kill_all()
        return {"killed_count": count}

    @application.post("/api/agent/undo")
    async def undo(request: UndoRequest) -> dict[str, Any]:
        """
        가장 최근에 되돌릴 수 있는 작업을 취소한다.

        되돌릴 수 있는 것: 파일 저장 (이전 내용 복원)
        되돌릴 수 없는 것: 마우스 클릭, 키 입력 (이미 발생한 조작)
        """
        manager = get_run_manager()
        try:
            description = await manager.runtime.undo_last(request.run_id or "")
        except UndoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"undone": description, "can_undo": manager.runtime.undo_manager.can_undo}

    @application.get("/api/agent/actions")
    async def actions(run_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        """
        액션 기록(./logs/actions.jsonl)을 조회한다.

        Args:
            run_id: 특정 실행만 조회하려면 지정
            limit: 최근 몇 건을 볼지
        """
        manager = get_run_manager()
        logger_ = manager.runtime.action_logger
        records = logger_.read_run(run_id) if run_id else logger_.read_all()
        return {"count": len(records), "actions": records[-limit:]}

    @application.websocket("/ws/agent/{run_id}")
    async def agent_events(websocket: WebSocket, run_id: str) -> None:
        """
        실행 진행 상황을 실시간으로 전송한다.

        전송되는 이벤트 종류:
          run_started / step_started / tool_call / tool_result /
          approval_required / approval_resolved / step_finished /
          run_killed / run_finished
        """
        await websocket.accept()

        if app_state.runtime is None:
            await websocket.send_json(
                {"type": "error", "payload": {"message": "백엔드가 준비되지 않았습니다."}}
            )
            await websocket.close()
            return

        bus = app_state.runtime.event_bus
        queue = bus.subscribe(run_id)

        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event.to_dict())
                if event.type == "run_finished":
                    break
        except WebSocketDisconnect:
            logger.debug("WebSocket 연결이 끊어졌습니다: %s", run_id)
        finally:
            bus.unsubscribe(run_id, queue)


app = create_app()
