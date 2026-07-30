@echo off
REM ============================================================
REM  PFM-Agent 통합 실행 (백엔드 + 프론트엔드)
REM  - 실행 전 점검 (설정 / 라이브러리 / 폴더 / 포트 / 도구 서버)
REM  - 문제가 있으면 한글 안내 후 중단
REM  - 이상 없으면 백엔드 + 화면 실행
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================================
echo   PFM-Agent 를 시작합니다.
echo ============================================================
echo.

REM --- 가상환경 존재 확인 (점검 스크립트 자체를 돌리기 위해 필요) ---
if not exist backend\.venv (
    echo   [!] 설치가 완료되지 않았습니다.
    echo       first_time_setup.bat 를 먼저 더블클릭해 주세요.
    echo.
    pause
    exit /b 1
)

REM --- [1/2] 실행 전 점검 ---
echo [1/2] 실행 전 점검 중... (도구 서버를 실제로 켜서 확인합니다)
echo.
cd backend
.venv\Scripts\python.exe ..\scripts\preflight_check.py
set PREFLIGHT=%errorlevel%
cd ..

if not "%PREFLIGHT%"=="0" (
    echo.
    echo   위 문제를 해결한 뒤 다시 실행해 주세요.
    echo.
    pause
    exit /b 1
)
echo.

REM --- [2/2] 백엔드 + 화면 실행 ---
echo [2/2] 백엔드 서버와 화면을 실행합니다...
start "PFM-Agent Backend" cmd /c "cd /d "%~dp0backend" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8756"

REM 백엔드가 준비될 시간을 준다.
timeout /t 5 /nobreak >nul

if exist frontend\node_modules (
    start "PFM-Agent" cmd /c "cd /d "%~dp0frontend" && pnpm tauri dev"
) else (
    echo   - 화면(프론트엔드)이 설치되지 않아 백엔드만 실행합니다.
    echo     브라우저에서 http://127.0.0.1:8756/docs 로 확인할 수 있습니다.
)

echo.
echo ============================================================
echo   PFM-Agent 가 실행되었습니다.
echo.
echo   * 종료하려면 열린 검은 창들을 닫으세요.
echo   * 비상 정지는 ESC 키 또는 화면의 빨간 정지 버튼을 사용하세요.
echo   * 작업 기록은 logs\actions.jsonl 에 남습니다.
echo ============================================================
echo.
exit /b 0
