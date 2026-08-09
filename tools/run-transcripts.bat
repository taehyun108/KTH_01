@echo off
setlocal EnableDelayedExpansion
REM ==================================================================
REM  KTH_01 - fetch YouTube transcripts from this PC and push them.
REM
REM  GitHub Actions runner IPs are blocked by YouTube, so transcripts
REM  never load there. A home connection is not blocked, so this PC
REM  fetches the transcripts and GitHub still does the summarising.
REM
REM  Usage
REM    run-transcripts.bat                      fetch and push
REM    run-transcripts.bat --dry-run            list targets only
REM    run-transcripts.bat --limit 5 --no-push  fetch 5, do not push
REM    run-transcripts.bat --auto               no pause (scheduler)
REM
REM  NOTE: keep this file ASCII-only. cmd.exe reads batch files in the
REM  OEM code page before chcp takes effect, so Korean text here can
REM  come out garbled. All Korean output comes from the Python script.
REM ==================================================================

chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM --auto is consumed here; everything else goes to Python.
set AUTO=0
set PYARGS=
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--auto" (set AUTO=1) else (set PYARGS=!PYARGS! %~1)
shift
goto parse
:parsed

REM Repository root = parent of the folder holding this file.
cd /d "%~dp0.."

REM Prefer "python"; fall back to the "py" launcher.
set PY=python
where python >nul 2>nul || set PY=py

echo.
echo [1/3] Updating the repository...
git pull --rebase --autostash
if errorlevel 1 (
  echo.
  echo   git pull FAILED - check your internet connection or git login.
  goto hold
)

echo.
echo [2/3] Fetching transcripts...
%PY% scripts\fetch_transcripts_local.py !PYARGS!
if errorlevel 1 (
  echo.
  echo   Transcript step FAILED - see the messages above.
  goto hold
)

echo.
echo [3/3] Done.

:hold
if "%AUTO%"=="1" exit /b 0
echo.
pause
