@echo off
REM ============================================================
REM  P-Agent 최초 설치 스크립트 (딱 한 번만 실행)
REM  - uv 설치 확인/준비
REM  - 백엔드 가상환경(.venv) 생성 + 의존성 설치
REM  - 프론트엔드 의존성 설치
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

REM --- [1/6] uv 설치 확인 ---
echo [1/6] Python 패키지 관리자(uv) 확인 중...
where uv >nul 2>nul
if errorlevel 1 (
    echo   - uv 가 없어 설치를 시도합니다...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    where uv >nul 2>nul
    if errorlevel 1 (
        echo   [!] uv 자동 설치에 실패했습니다.
        echo       인터넷이 차단된 환경이라면, 개발자에게 uv 가 포함된 USB 를 요청하세요.
        goto :error
    )
)
echo   - uv 준비 완료.
echo.

REM --- [2/6] 백엔드 가상환경 + 의존성 ---
echo [2/6] 백엔드 가상환경(.venv) 생성 및 라이브러리 설치 중...
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

REM --- [3/6] 화면 인식 기능 (선택) ---
echo [3/6] 화면 인식(OCR) 라이브러리 설치 중... (선택 기능)
cd backend
uv sync --extra vision
if errorlevel 1 (
    echo   - [건너뜀] 화면 인식 라이브러리를 설치하지 못했습니다.
    echo             화면 인식을 제외한 기능은 정상 동작합니다.
)
cd ..
echo.

REM --- [4/6] 프론트엔드 의존성 (pnpm) ---
echo [4/6] 프론트엔드 라이브러리 설치 중...
where pnpm >nul 2>nul
if errorlevel 1 (
    echo   - [건너뜀] pnpm 이 없습니다. 화면 없이 백엔드만 사용할 수 있습니다.
) else (
    cd frontend
    if exist package.json (
        pnpm install
        if errorlevel 1 echo   - [경고] 프론트엔드 설치에 실패했습니다.
    )
    cd ..
)
echo.

REM --- [5/6] 로컬 모델 다운로드 ---
echo [5/6] AI 모델 파일 준비 중 (문서 검색 / 글자 인식)...
echo       ※ 사내망에서는 실패가 정상이며, 앱은 대체 방식으로 동작합니다.
cd backend
uv run python ..\scripts\download_models.py
cd ..
echo.

REM --- [6/6] .env 생성 ---
echo [6/6] 설정 파일(.env) 준비 중...
if exist .env (
    echo   - 이미 .env 파일이 있어 그대로 둡니다.
) else (
    copy /Y .env.example .env >nul
    echo   - .env.example -^> .env 복사 완료.
)
echo.

echo ============================================================
echo   설치가 완료되었습니다.
echo.
echo   다음 순서로 진행하세요.
echo     1) .env 파일을 메모장으로 열기
echo     2) LLM_PROVIDER=pgpt 로 두고
echo        PGPT_BASE_URL / PGPT_API_KEY / PGPT_MODEL 에
echo        회사에서 받은 값을 입력 후 저장
echo     3) run_all.bat 를 더블클릭해 실행
echo ============================================================
echo.
pause
exit /b 0

:error
echo.
echo ============================================================
echo   설치 중 문제가 발생했습니다. 위 메시지를 확인하세요.
echo      (logs 폴더와 함께 개발 담당자에게 문의하세요)
echo ============================================================
echo.
pause
exit /b 1
