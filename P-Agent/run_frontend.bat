@echo off
REM ============================================================
REM  P-Agent 프론트엔드 단독 실행 (Tauri + React)
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

if not exist frontend\package.json (
    echo [!] 프론트엔드가 아직 준비되지 않았습니다. (개발 진행 중)
    pause
    exit /b 1
)
if not exist frontend\node_modules (
    echo [!] node_modules 가 없습니다. first_time_setup.bat 를 먼저 실행하세요.
    pause
    exit /b 1
)

echo P-Agent 프론트엔드를 시작합니다...
cd frontend
pnpm tauri dev
pause
