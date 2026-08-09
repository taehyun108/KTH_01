@echo off
REM ==================================================================
REM  Register run-transcripts.bat to run twice a day.
REM
REM  The GitHub archive job runs at 09:00 and 21:00 KST. Transcripts
REM  must be pushed before that, so this schedules 08:20 and 20:20.
REM
REM  Administrator rights are NOT required - it registers under the
REM  current user account.
REM
REM  To remove:  uninstall-schedule.bat
REM
REM  NOTE: ASCII-only on purpose (see run-transcripts.bat).
REM ==================================================================

set BAT=%~dp0run-transcripts.bat

if not exist "%BAT%" (
  echo run-transcripts.bat not found next to this file.
  pause
  exit /b 1
)

echo.
echo Task    : KTH01-Transcripts-AM / -PM
echo Runs    : %BAT% --auto
echo Schedule: every day at 08:20 and 20:20
echo.

REM schtasks cannot put two times in one daily task, so register two.
REM Single quotes around the path are the reliable way to pass a path
REM containing spaces inside /tr.
schtasks /create /tn "KTH01-Transcripts-AM" /tr "'%BAT%' --auto" /sc daily /st 08:20 /f
if errorlevel 1 goto failed

schtasks /create /tn "KTH01-Transcripts-PM" /tr "'%BAT%' --auto" /sc daily /st 20:20 /f
if errorlevel 1 goto failed

echo.
echo Registered. It runs automatically whenever the PC is on at those
echo times. If the PC is off, that run is simply skipped - the website
echo keeps working exactly as it does today.
echo.
echo To test it right now:
echo     schtasks /run /tn "KTH01-Transcripts-AM"
echo.
pause
exit /b 0

:failed
echo.
echo Registration FAILED. Please send me the message above.
echo.
pause
exit /b 1
