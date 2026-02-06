#!/bin/bash
# ============================================================
#  NanoBot Multi-Bot Gateway - Process Isolation Mode
#  Ubuntu 专用启动脚本
#  每个 Bot 作为独立进程运行，拥有独立的飞书连接
# ============================================================

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  NanoBot Multi-Bot Gateway - Process Isolation Mode${NC}"
echo -e "${CYAN}  每个 Bot 作为独立进程运行${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

# -------------------------------------------
# 1. 检查 Python 环境
# -------------------------------------------
PYTHON_CMD=""
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
fi

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}[ERROR] 未找到 Python。请先安装 Python 3.11+：${NC}"
    echo ""
    echo "  sudo apt update && sudo apt install -y python3 python3-pip python3-venv"
    echo ""
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

echo -e "${GREEN}[OK]${NC} Python 版本: $PYTHON_VERSION"

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${YELLOW}[WARNING] 推荐使用 Python 3.11+，当前版本为 $PYTHON_VERSION${NC}"
    echo "  可通过以下命令升级："
    echo "  sudo apt install -y python3.11 python3.11-venv"
    echo ""
fi

# -------------------------------------------
# 2. 检查 pip
# -------------------------------------------
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo -e "${YELLOW}[INFO] pip 未安装，正在安装...${NC}"
    sudo apt update && sudo apt install -y python3-pip
fi

# -------------------------------------------
# 3. 检查并安装 nanobot
# -------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! $PYTHON_CMD -m nanobot --version &> /dev/null 2>&1; then
    echo -e "${YELLOW}[INFO] nanobot 未安装，正在从源码安装...${NC}"
    cd "$SCRIPT_DIR"
    $PYTHON_CMD -m pip install -e . --quiet
    if [ $? -ne 0 ]; then
        echo -e "${RED}[ERROR] nanobot 安装失败，请检查 Python 环境。${NC}"
        exit 1
    fi
    echo -e "${GREEN}[OK]${NC} nanobot 安装成功"
else
    NANOBOT_VERSION=$($PYTHON_CMD -m nanobot --version 2>&1)
    echo -e "${GREEN}[OK]${NC} $NANOBOT_VERSION"
fi

# -------------------------------------------
# 4. 检查飞书 SDK
# -------------------------------------------
if ! $PYTHON_CMD -c "import lark_oapi" &> /dev/null 2>&1; then
    echo -e "${YELLOW}[INFO] 飞书 SDK 未安装，正在安装...${NC}"
    $PYTHON_CMD -m pip install lark-oapi --quiet
fi
echo -e "${GREEN}[OK]${NC} 飞书 SDK 已安装"

# -------------------------------------------
# 5. 检查配置文件
# -------------------------------------------
CONFIG_PATH="$HOME/.nanobot/config.json"

if [ ! -f "$CONFIG_PATH" ]; then
    echo ""
    echo -e "${YELLOW}[WARNING] 未找到配置文件: $CONFIG_PATH${NC}"
    echo ""
    echo "  请先创建配置文件。可以复制示例配置："
    echo ""
    echo -e "    ${CYAN}cp config.example.json $CONFIG_PATH${NC}"
    echo ""
    echo "  然后编辑配置文件，填入 API Key 和飞书应用凭证："
    echo ""
    echo -e "    ${CYAN}nano $CONFIG_PATH${NC}"
    echo ""
    echo "  注意：每个 Bot 需要独立的飞书应用 (appId + appSecret)。"
    echo ""
    exit 1
fi

echo -e "${GREEN}[OK]${NC} 配置文件: $CONFIG_PATH"

# -------------------------------------------
# 6. 显示当前 Bot 状态
# -------------------------------------------
echo ""
echo -e "${CYAN}[INFO] 当前 Bot 状态：${NC}"
$PYTHON_CMD -m nanobot status
echo ""

# -------------------------------------------
# 7. 启动 Gateway (进程隔离模式)
# -------------------------------------------
echo -e "${CYAN}[INFO] 正在启动多 Bot 网关 (进程隔离模式)...${NC}"
echo -e "${CYAN}[INFO] 每个 Bot 作为独立进程运行，拥有独立的飞书连接${NC}"
echo -e "${CYAN}[INFO] 如果某个 Bot 崩溃，将自动重启${NC}"
echo -e "${CYAN}[INFO] 按 Ctrl+C 停止所有 Bot${NC}"
echo ""

# 捕获 Ctrl+C 信号，优雅退出
trap 'echo ""; echo -e "${YELLOW}[INFO] 正在停止所有 Bot 进程...${NC}"; exit 0' INT TERM

$PYTHON_CMD -m nanobot gateway --verbose

echo ""
echo -e "${GREEN}[INFO] Gateway 已停止。${NC}"
