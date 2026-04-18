@echo off
setlocal
cd /d "%~dp0"

powershell -ExecutionPolicy Bypass -File ".\scripts\setup.ps1"
if errorlevel 1 (
    echo.
    echo [install] Installation failed.
    pause
    exit /b 1
)

echo.
echo [install] Installation complete.
choice /M "Launch ChipSeeker now"
if errorlevel 2 exit /b 0

call "%~dp0Start_ChipSeeker.bat"
