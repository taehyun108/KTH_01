@echo off
REM ============================================================
REM  P-Agent 통합 실행 (백엔드 + 프론트엔드 동시)
REM  - .env / .venv 존재 확인
REM  - MCP 서버 헬스체크
REM  - 백엔드 + 프론트엔드 실행
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================================
echo   P-Agent 를 시작합니다.
echo ============================================================
echo.

REM --- [1/3] 사전 점검 ---
echo [1/3] 실행 환경 점검 중...
if not exist .env (
    echo   [!] .env 파일이 없습니다. first_time_setup.bat 를 먼저 실행하세요.
    goto :error
)
if not exist backend\.venv (
    echo   [!] 가상환경(.venv)이 없습니다. first_time_setup.bat 를 먼저 실행하세요.
    goto :error
)
echo   - .env / .venv 확인 완료.
echo.

REM --- [2/3] MCP 서버 헬스체크 ---
echo [2/3] 내부 도구 서버(MCP) 헬스체크 중...
cd backend
call .venv\Scripts\activate.bat
python -m app.mcp_client --healthcheck
if errorlevel 1 (
    echo   [!] 일부 MCP 서버가 정상 시작되지 않았습니다. logs\ 폴더를 확인하세요.
    echo       (계속 진행하지만 일부 기능이 제한될 수 있습니다)
)
cd ..
echo.

REM --- [3/3] 백엔드 + 프론트엔드 실행 ---
echo [3/3] 백엔드 서버와 화면을 실행합니다...
start "P-Agent Backend" cmd /c "cd /d "%~dp0backend" && call .venv\Scripts\activate.bat && uv run uvicorn app.main:app --host 127.0.0.1 --port 8756"

REM 백엔드가 뜰 시간을 잠깐 대기
timeout /t 3 /nobreak >nul

if exist frontend\package.json (
    start "P-Agent Frontend" cmd /c "cd /d "%~dp0frontend" && pnpm tauri dev"
) else (
    echo   - 프론트엔드가 아직 준비되지 않아 백엔드만 실행합니다. (개발 진행 중)
)

echo.
echo ============================================================
echo   ✅ P-Agent 가 실행되었습니다.
echo   종료하려면 열린 창들을 닫으세요.
echo   비상 정지는 ESC 키(Kill Switch)를 사용하세요.
echo ============================================================
echo.
exit /b 0

:error
echo.
pause
exit /b 1
