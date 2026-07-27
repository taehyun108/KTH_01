"""
P-Agent 전역 설정 로더.

포터블(Portable) 원칙:
  - 프로젝트 루트는 이 파일의 위치로부터 상대적으로 계산한다.
      settings.py -> config -> app -> backend -> (프로젝트 루트)
  - 모든 경로 설정은 프로젝트 루트 기준 상대경로로 해석한다.
  - 시스템 환경변수에 의존하지 않는다. 값은 `.env` 파일에서만 읽는다.
    (테스트/CI 편의를 위해 이미 설정된 OS 환경변수는 .env 값으로 덮어쓴다)
  - 드라이브 문자(C:, D:)를 하드코딩하지 않는다.

사용 예:
    from app.config.settings import get_settings

    settings = get_settings()
    print(settings.llm_provider)      # "anthropic"
    print(settings.output_dir)        # <프로젝트루트>/output (절대 Path 객체)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

# ------------------------------------------------------------
# 프로젝트 루트 계산 (절대경로 하드코딩 금지)
#   이 파일: <루트>/backend/app/config/settings.py
#   parents[0]=config, [1]=app, [2]=backend, [3]=<루트>
# ------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

#: `.env` 탐색 순서 (먼저 발견되는 것을 사용)
_ENV_CANDIDATES: tuple[Path, ...] = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "backend" / ".env",
)


def find_env_file() -> Path | None:
    """사용할 `.env` 파일 경로를 찾는다. 없으면 None."""
    for candidate in _ENV_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _read_env() -> dict[str, str]:
    """
    `.env` 값을 읽어 dict 로 반환한다.

    우선순위: `.env` 값 > OS 환경변수
    (포터블 원칙상 `.env` 가 항상 진실의 원천이며,
     `.env` 에 없는 키에 한해 OS 환경변수를 참고한다.)
    """
    merged: dict[str, str] = {k: v for k, v in os.environ.items()}
    env_file = find_env_file()
    if env_file is not None:
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                merged[key] = value
    return merged


def _resolve_path(raw: str) -> Path:
    """
    설정값 경로 문자열을 프로젝트 루트 기준 절대 Path 로 변환한다.

    - "./output", "output"  -> <루트>/output
    - 이미 절대경로면 그대로 사용 (사용자가 의도적으로 지정한 경우)
    """
    path = Path(raw.strip())
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _as_bool(raw: str | None, default: bool = False) -> bool:
    """문자열 설정값을 bool 로 변환한다. ('true'/'1'/'yes'/'on' → True)"""
    if raw is None:
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on", "y"}


def _as_int(raw: str | None, default: int) -> int:
    """문자열 설정값을 int 로 변환한다. 변환 실패 시 기본값."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    """P-Agent 전역 설정값 (읽기 전용)."""

    # --- [1] LLM Provider ---
    llm_provider: str = "anthropic"

    pgpt_base_url: str = ""
    pgpt_api_key: str = ""
    pgpt_model: str = "pgpt-default"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    # --- [2] 서버 ---
    backend_host: str = "127.0.0.1"
    backend_port: int = 8756
    frontend_port: int = 5173

    # --- [3] RAG / 임베딩 ---
    embedding_model_path: Path = field(default_factory=lambda: PROJECT_ROOT / "models" / "bge-m3")
    chroma_db_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "chroma")
    rag_top_k: int = 5

    # --- [4] Vision / OCR ---
    omniparser_model_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "models" / "omniparser"
    )
    ocr_lang: str = "korean"

    # --- [5] 웹 검색 (선택 기능) ---
    web_search_enabled: bool = False
    web_search_api_key: str = ""

    # --- [6] 안전장치 ---
    kill_switch_key: str = "esc"
    require_approval: bool = True
    action_log_path: Path = field(default_factory=lambda: PROJECT_ROOT / "logs" / "actions.jsonl")

    # --- [7] 경로 ---
    output_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "output")
    log_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")

    # --- [8] 실행 모드 ---
    app_env: str = "development"
    log_level: str = "INFO"

    # --- 메타 ---
    project_root: Path = PROJECT_ROOT

    @property
    def is_production(self) -> bool:
        """배포(사내망) 모드 여부."""
        return self.app_env.strip().lower() == "production"

    def ensure_runtime_dirs(self) -> None:
        """
        런타임 산출물 폴더를 생성한다. (모두 프로젝트 폴더 내부)

        앱 기동 시 1회 호출하여 data/logs/output 이 없어도 동작하도록 한다.
        """
        for directory in (self.data_dir, self.log_dir, self.output_dir, self.chroma_db_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.action_log_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """`.env` 를 읽어 Settings 인스턴스를 생성한다. (캐시 없음)"""
    env = _read_env()

    def get(key: str, default: str = "") -> str:
        value = env.get(key)
        return default if value is None else value.strip()

    return Settings(
        # [1] LLM Provider
        llm_provider=get("LLM_PROVIDER", "anthropic").lower(),
        pgpt_base_url=get("PGPT_BASE_URL"),
        pgpt_api_key=get("PGPT_API_KEY"),
        pgpt_model=get("PGPT_MODEL", "pgpt-default"),
        anthropic_api_key=get("ANTHROPIC_API_KEY"),
        anthropic_model=get("ANTHROPIC_MODEL", "claude-opus-5"),
        openai_api_key=get("OPENAI_API_KEY"),
        openai_base_url=get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=get("OPENAI_MODEL", "gpt-4o"),
        # [2] 서버
        backend_host=get("BACKEND_HOST", "127.0.0.1"),
        backend_port=_as_int(env.get("BACKEND_PORT"), 8756),
        frontend_port=_as_int(env.get("FRONTEND_PORT"), 5173),
        # [3] RAG
        embedding_model_path=_resolve_path(get("EMBEDDING_MODEL_PATH", "./models/bge-m3")),
        chroma_db_dir=_resolve_path(get("CHROMA_DB_DIR", "./data/chroma")),
        rag_top_k=_as_int(env.get("RAG_TOP_K"), 5),
        # [4] Vision / OCR
        omniparser_model_path=_resolve_path(get("OMNIPARSER_MODEL_PATH", "./models/omniparser")),
        ocr_lang=get("OCR_LANG", "korean"),
        # [5] 웹 검색
        web_search_enabled=_as_bool(env.get("WEB_SEARCH_ENABLED"), False),
        web_search_api_key=get("WEB_SEARCH_API_KEY"),
        # [6] 안전장치
        kill_switch_key=get("KILL_SWITCH_KEY", "esc").lower(),
        require_approval=_as_bool(env.get("REQUIRE_APPROVAL"), True),
        action_log_path=_resolve_path(get("ACTION_LOG_PATH", "./logs/actions.jsonl")),
        # [7] 경로
        output_dir=_resolve_path(get("OUTPUT_DIR", "./output")),
        log_dir=_resolve_path(get("LOG_DIR", "./logs")),
        data_dir=_resolve_path(get("DATA_DIR", "./data")),
        # [8] 실행 모드
        app_env=get("APP_ENV", "development"),
        log_level=get("LOG_LEVEL", "INFO").upper(),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """전역 설정 싱글턴. (앱 전체에서 이 함수를 통해 설정에 접근)"""
    return load_settings()


def reload_settings() -> Settings:
    """설정 캐시를 비우고 다시 로드한다. (테스트/설정 변경 시 사용)"""
    get_settings.cache_clear()
    return get_settings()
