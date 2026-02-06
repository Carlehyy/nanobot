#!/bin/bash
# ============================================================
#  NanoBot Multi-Bot Gateway - Process Isolation Mode
#  通用 Linux/macOS 启动脚本
#  每个 Bot 作为独立进程运行，拥有独立的飞书连接
# ============================================================

set -e

echo "============================================================"
echo "  NanoBot Multi-Bot Gateway - Process Isolation Mode"
echo "  每个 Bot 作为独立进程运行"
echo "============================================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.11+"
    exit 1
fi

# Check nanobot
if ! python3 -m nanobot --version &> /dev/null 2>&1; then
    echo "[INFO] Installing nanobot..."
    pip3 install -e .
fi

# Check lark-oapi
if ! python3 -c "import lark_oapi" &> /dev/null 2>&1; then
    echo "[INFO] Installing Feishu SDK..."
    pip3 install lark-oapi
fi

# Check config
CONFIG_PATH="$HOME/.nanobot/config.json"
if [ ! -f "$CONFIG_PATH" ]; then
    echo "[ERROR] Config not found at $CONFIG_PATH"
    echo "Please copy config.example.json and edit it."
    echo "Note: Each bot needs its own Feishu app (appId + appSecret)."
    exit 1
fi

echo "[INFO] Starting multi-bot gateway (Process Isolation Mode)..."
echo "[INFO] Each bot runs as an independent process with its own Feishu connection."
echo "[INFO] Press Ctrl+C to stop all bots."
echo ""

trap 'echo ""; echo "[INFO] Stopping all bot processes..."; exit 0' INT TERM

python3 -m nanobot gateway --verbose
