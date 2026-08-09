@echo off
REM Remove the scheduled runs. The transcript cache and the repository
REM are left untouched. ASCII-only on purpose (see run-transcripts.bat).

schtasks /delete /tn "KTH01-Transcripts-AM" /f 2>nul
schtasks /delete /tn "KTH01-Transcripts-PM" /f 2>nul

echo.
echo Scheduled runs removed.
echo You can still run tools\run-transcripts.bat by hand at any time.
echo.
pause
