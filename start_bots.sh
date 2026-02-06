#!/bin/bash
# nanobot Multi-Bot Group Chat Gateway Launcher

echo "============================================"
echo "  nanobot Multi-Bot Group Chat Gateway"
echo "============================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 not found. Please install Python 3.11+."
    exit 1
fi

# Check nanobot
if ! python3 -m nanobot --version &> /dev/null; then
    echo "[INFO] nanobot not installed. Installing from source..."
    pip3 install -e .
fi

# Check config
CONFIG_PATH="$HOME/.nanobot/config.json"
if [ ! -f "$CONFIG_PATH" ]; then
    echo "[WARNING] Config file not found at $CONFIG_PATH"
    echo ""
    echo "Please create the config file first. Run:"
    echo "  nanobot onboard"
    echo ""
    echo "Then edit $CONFIG_PATH to add your bots and feishu settings."
    exit 1
fi

echo "[INFO] Starting nanobot gateway..."
echo "[INFO] Config: $CONFIG_PATH"
echo "[INFO] Press Ctrl+C to stop all bots."
echo ""

python3 -m nanobot gateway

echo ""
echo "[INFO] Gateway stopped."
