@echo off
REM ============================================================
REM  PFM-Agent 화면 단독 실행 (Tauri + React)
REM  백엔드가 이미 실행 중이어야 합니다.
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist frontend\node_modules (
    echo [!] 화면 라이브러리가 설치되지 않았습니다.
    echo     first_time_setup.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)

echo PFM-Agent 화면을 시작합니다...
echo   (백엔드가 실행 중이어야 정상 동작합니다)
echo.
cd frontend
pnpm tauri dev
pause
