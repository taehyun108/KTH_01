@echo off
REM ============================================================
REM  P-Agent 백엔드 단독 실행 (FastAPI + LangGraph)
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist .env (
    echo [!] .env 파일이 없습니다. first_time_setup.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)
if not exist backend\.venv (
    echo [!] 가상환경(.venv)이 없습니다. first_time_setup.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)

echo P-Agent 백엔드를 시작합니다...
cd backend
call .venv\Scripts\activate.bat
uv run uvicorn app.main:app --host 127.0.0.1 --port 8756 --reload
pause
