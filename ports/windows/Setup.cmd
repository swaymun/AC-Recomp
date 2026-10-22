@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Setup.ps1" %*
set "ACR_RESULT=%ERRORLEVEL%"
if not "%ACR_RESULT%"=="0" echo Setup did not finish. Read the error above, then run Setup again to resume.
pause
exit /b %ACR_RESULT%
