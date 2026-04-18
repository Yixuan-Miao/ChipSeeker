@echo off
setlocal
cd /d "%~dp0"

echo This will remove the local ChipSeeker environment and generated data in this folder:
echo   - .venv
echo   - local_data
echo   - config.local.json
echo   - .pytest_cache
echo.
choice /M "Continue with uninstall"
if errorlevel 2 (
    echo.
    echo [uninstall] Cancelled.
    pause
    exit /b 0
)

powershell -ExecutionPolicy Bypass -File ".\scripts\uninstall.ps1"
if errorlevel 1 (
    echo.
    echo [uninstall] Uninstall failed.
    pause
    exit /b 1
)

echo.
echo [uninstall] Uninstall complete.
pause
