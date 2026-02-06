@echo off
chcp 65001 >nul 2>&1
title nanobot Multi-Bot Gateway

echo ============================================
echo   nanobot Multi-Bot Group Chat Gateway
echo ============================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.11+ first.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Check if nanobot is installed
python -m nanobot --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] nanobot not installed. Installing from source...
    pip install -e . 
    if errorlevel 1 (
        echo [ERROR] Failed to install nanobot. Please check your Python environment.
        pause
        exit /b 1
    )
)

REM Check if config exists
if not exist "%USERPROFILE%\.nanobot\config.json" (
    echo [WARNING] Config file not found at %USERPROFILE%\.nanobot\config.json
    echo.
    echo Please create the config file first. Run:
    echo   nanobot onboard
    echo.
    echo Then edit %USERPROFILE%\.nanobot\config.json to add your bots and feishu settings.
    pause
    exit /b 1
)

echo [INFO] Starting nanobot gateway...
echo [INFO] Config: %USERPROFILE%\.nanobot\config.json
echo [INFO] Press Ctrl+C to stop all bots.
echo.

python -m nanobot gateway

echo.
echo [INFO] Gateway stopped.
pause
