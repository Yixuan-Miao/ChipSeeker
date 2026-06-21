@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\Start_ChipSeeker_AutoStop.ps1"
) else (
    echo [start] .venv was not found.
    echo [start] Run Install_ChipSeeker.bat first, or run scripts\setup.ps1 manually.
    pause
    exit /b 1
)
