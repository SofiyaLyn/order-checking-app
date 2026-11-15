@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 launch.py
    if errorlevel 1 pause
    exit /b
)
where python >nul 2>nul
if %errorlevel%==0 (
    python launch.py
    if errorlevel 1 pause
    exit /b
)
echo Python 3.10 or newer is required. Install it from python.org, then open this file again.
pause

