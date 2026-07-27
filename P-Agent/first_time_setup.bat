@echo off
REM ============================================================
REM  P-Agent 최초 설치 스크립트 (딱 한 번만 실행)
REM  - uv 설치 확인/준비
REM  - 백엔드 가상환경(.venv) 생성 + 의존성 설치
REM  - 로컬 모델 다운로드 (인터넷 가능 시)
REM  - .env.example -> .env 자동 복사
REM  ※ 모든 경로는 이 배치파일 위치 기준 상대경로
REM ============================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   P-Agent 최초 설치를 시작합니다.
echo   (최초 1회는 수 분 ~ 십수 분 걸릴 수 있습니다)
echo ============================================================
echo.

REM --- [1/5] uv 설치 확인 ---
echo [1/5] Python 패키지 관리자(uv) 확인 중...
where uv >nul 2>nul
if errorlevel 1 (
    echo   - uv 가 없어 설치를 시도합니다...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    where uv >nul 2>nul
    if errorlevel 1 (
        echo   [!] uv 자동 설치에 실패했습니다.
        echo       인터넷이 차단된 환경이라면, 개발자에게 uv 가 포함된 USB 를 요청하세요.
        goto :error
    )
)
echo   - uv 준비 완료.
echo.

REM --- [2/5] 백엔드 가상환경 + 의존성 ---
echo [2/5] 백엔드 가상환경(.venv) 생성 및 라이브러리 설치 중...
cd backend
uv sync
if errorlevel 1 (
    echo   [!] 라이브러리 설치에 실패했습니다. 인터넷 연결 또는 사내 미러 설정을 확인하세요.
    cd ..
    goto :error
)
cd ..
echo   - 백엔드 환경 준비 완료.
echo.

REM --- [3/5] 프론트엔드 의존성 (pnpm) ---
echo [3/5] 프론트엔드 라이브러리 설치 중...
where pnpm >nul 2>nul
if errorlevel 1 (
    echo   - pnpm 이 없어 건너뜁니다. (프론트엔드 빌드 시 개발자에게 문의)
) else (
    cd frontend
    if exist package.json (
        pnpm install
    ) else (
        echo   - package.json 이 아직 없어 건너뜁니다. (개발 진행 중)
    )
    cd ..
)
echo.

REM --- [4/5] 로컬 모델 다운로드 ---
echo [4/5] AI 모델 파일 준비 중 (BGE-M3 / OmniParser / PaddleOCR)...
if exist backend\.venv (
    call backend\.venv\Scripts\activate.bat
    python scripts\download_models.py
    if errorlevel 1 (
        echo   [!] 모델 다운로드에 실패했습니다.
        echo       폐쇄망 환경이면 개발자가 models\ 폴더를 채운 USB 를 전달해야 합니다.
    )
) else (
    echo   - 가상환경이 없어 모델 다운로드를 건너뜁니다.
)
echo.

REM --- [5/5] .env 생성 ---
echo [5/5] 설정 파일(.env) 준비 중...
if exist .env (
    echo   - 이미 .env 파일이 있어 그대로 둡니다.
) else (
    copy /Y .env.example .env >nul
    echo   - .env.example -^> .env 복사 완료. (P-GPT 값은 직접 입력하세요)
)
echo.

echo ============================================================
echo   ✅ 설치가 완료되었습니다.
echo   다음: .env 파일에 사내 P-GPT 정보를 입력한 뒤,
echo         run_all.bat 를 더블클릭하여 실행하세요.
echo ============================================================
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo   ❌ 설치 중 문제가 발생했습니다. 위 메시지를 확인하세요.
echo      (logs\ 폴더와 함께 개발 담당자에게 문의하세요)
echo ============================================================
echo.
pause
exit /b 1
