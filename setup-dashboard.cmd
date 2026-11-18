@echo off

REM =============================================================================
REM Unified Dashboard Setup for Paperclip+Herdr
REM File: setup-dashboard.cmd
REM Version: 1.0.0
REM =============================================================================
REM Creator / سازنده:
REM   https://github.com/hamzeh-asadi
REM   https://t.me/Asadi_hamzeh
REM =============================================================================

setlocal

title Unified Dashboard Setup for Paperclip+Herdr

cd /d "%~dp0"

if not exist "%~dp0setup-dashboard.ps1" (
    echo [ERROR] setup-dashboard.ps1 was not found next to this file.
    pause
    exit /b 1
)

REM Remove the "downloaded from internet" mark, then run the script for this run only.
powershell.exe -NoProfile -Command "Unblock-File -LiteralPath '%~dp0setup-dashboard.ps1'" >nul 2>&1

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-dashboard.ps1" %*

set EXITCODE=%ERRORLEVEL%

echo.
if %EXITCODE% NEQ 0 (echo [ERROR] Setup finished with exit code %EXITCODE%.) else (echo [DONE] Setup finished.)

pause

exit /b %EXITCODE%