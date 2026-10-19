@echo off
setlocal
echo ===================================================================
echo   AOUL - AI Robotics Copilot
echo   Actuator * Orientation * Undefined-behavior * Locator
echo ===================================================================
echo Starting AOUL Local Robotics Workspace on Windows...

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python run.py %*
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        py run.py %*
    ) else (
        echo [ERROR] Python 3 was not found in your system PATH!
        echo Please install Python 3.9+ from https://www.python.org/ or the Microsoft Store.
        pause
    )
)
