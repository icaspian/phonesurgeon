@echo off
title PhoneSurgeon - Advanced ADB Toolkit
color 0B
cls

echo.
echo     ╔══════════════════════════════════════════════╗
echo     ║   PhoneSurgeon - Advanced ADB Toolkit        ║
echo     ╚══════════════════════════════════════════════╝
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo   [!] Python not found. Checking py launcher...
    py --version >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   [ERROR] Python is not installed!
        echo   Download from: https://www.python.org/downloads/
        echo.
        pause
        exit /b 1
    ) else (
        echo   [OK] Python found via py launcher
        py "%~dp0phonesurgeon.py"
        exit /b %errorlevel%
    )
)

echo   [OK] Python found
echo   [*] Launching PhoneSurgeon...
echo.

python "%~dp0phonesurgeon.py"
exit /b %errorlevel%
