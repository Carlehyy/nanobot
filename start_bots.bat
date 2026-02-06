@echo off
chcp 65001 >nul 2>&1
title NanoBot Multi-Bot Gateway (Process Isolation)

echo ============================================================
echo   NanoBot Multi-Bot Gateway - Process Isolation Mode
echo   Each bot runs as an independent process
echo ============================================================
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

REM Check if lark-oapi is installed
python -c "import lark_oapi" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing Feishu SDK...
    pip install lark-oapi
)

REM Check if config exists
if not exist "%USERPROFILE%\.nanobot\config.json" (
    echo [WARNING] Config file not found at %USERPROFILE%\.nanobot\config.json
    echo.
    echo Please create the config file first. You can copy config.example.json:
    echo   copy config.example.json %USERPROFILE%\.nanobot\config.json
    echo.
    echo Then edit it to fill in your API keys and Feishu app credentials.
    echo Each bot needs its own Feishu app (appId + appSecret).
    pause
    exit /b 1
)

echo [INFO] Starting multi-bot gateway (Process Isolation Mode)...
echo [INFO] Config: %USERPROFILE%\.nanobot\config.json
echo [INFO] Each bot runs as an independent process with its own Feishu connection.
echo [INFO] If a bot crashes, it will be automatically restarted.
echo [INFO] Press Ctrl+C to stop all bots.
echo.

python -m nanobot gateway --verbose

echo.
echo [INFO] Gateway stopped.
pause
