# nanobot 多 Bot 飞书群聊协作平台 - 用户操作指南

## 1. 简介

欢迎使用 `nanobot` 多 Bot 协作平台！

本文档将指导您如何在您的 Windows 电脑上完成以下操作：
-   配置多个大语言模型（LLM）的 API Keys。
-   启动多个独立的 Bot 实例。
-   将所有 Bot 接入同一个飞书（Lark）群聊，实现“群策群力”的 AI 协作体验。

每个 Bot 都可以拥有自己独特的身份（Persona）和 API Key，它们能够共同读取群聊消息并参与讨论，为您提供多角度、高质量的反馈。

---

## 2. 环境准备

在开始之前，请确保您的 Windows 系统已安装以下软件：

-   **Python 3.11 或更高版本**：请从 [Python 官网](https://www.python.org/downloads/) 下载并安装。在安装时，请务必勾选 `Add Python to PATH` 选项。
-   **Git**：请从 [Git 官网](https://git-scm.com/download/win) 下载并安装。

您可以通过在命令提示符（CMD）或 PowerShell 中运行以下命令来验证安装是否成功：

```bash
python --version
git --version
```

---

## 3. 获取与安装

### 步骤 3.1: 克隆代码仓库

首先，打开命令提示符（CMD），使用 `git` 命令克隆我们为您准备好的 `chat-bot` 分支代码。

```bash
# 找一个您喜欢的位置存放项目，然后运行以下命令
git clone -b chat-bot https://github.com/Carlehyy/nanobot.git

# 进入项目目录
cd nanobot
```

### 步骤 3.2: 安装项目依赖

项目使用 `pip` 进行包管理。在 `nanobot` 目录中，运行以下命令安装所有必需的依赖项：

```bash
pip install -e .
```

安装完成后，`nanobot` 命令就已经在您的系统中可用了。

---

## 4. 飞书机器人配置

为了让 Bot 能够接入飞书群聊，您需要创建一个飞书机器人应用。

1.  **创建应用**：访问 [飞书开放平台](https://open.feishu.cn/app) 并创建一个新的“企业自建应用”。
2.  **获取凭证**：在应用的“凭证与基础信息”页面，找到并记录下 **App ID** 和 **App Secret**。
3.  **开通机器人权限**：
    *   在“应用功能” -> “机器人”页面，启用机器人能力。
4.  **配置事件订阅**：
    *   在“事件订阅”页面，找到并添加 `im.message.receive_v1` 事件。这个事件允许机器人接收消息。
5.  **发布应用**：完成配置后，创建并发布一个新版本。
6.  **邀请入群**：将创建好的机器人邀请到您希望它参与讨论的飞书群聊中。

---

## 5. 核心配置

所有 Bot 的行为都由一个名为 `config.json` 的文件控制。我们将通过 `nanobot` 命令来生成和配置它。

### 步骤 5.1: 生成默认配置

在命令提示符中运行以下命令，程序会自动在您的用户目录下创建 `~/.nanobot/config.json` 文件。

```bash
nanobot onboard
```

### 步骤 5.2: 编辑配置文件

使用您喜欢的文本编辑器（如 VS Code 或记事本）打开 `C:\Users\YourUsername\.nanobot\config.json` 文件，并将其内容替换为以下模板。

**重要提示**：请将模板中的占位符（如 `YOUR_..._KEY`）替换为您自己的真实信息。

```json
{
  "bots": [
    {
      "name": "分析师小智",
      "model": "glm-4.5-flash",
      "apiKey": "YOUR_ZHIPU_API_KEY_1",
      "persona": "你是一个严谨的分析师，擅长深入分析问题、拆解任务、提供数据支持和逻辑推理。"
    },
    {
      "name": "创意师小慧",
      "model": "glm-4.5-flash",
      "apiKey": "YOUR_ZHIPU_API_KEY_2",
      "persona": "你是一个充满创意的思考者，擅长头脑风暴、提出新颖的想法和创新的解决方案。"
    },
    {
      "name": "总结师小明",
      "model": "glm-4.5-flash",
      "apiKey": "YOUR_ZHIPU_API_KEY_3",
      "persona": "你是一个高效的总结者，擅长归纳讨论要点、整合不同观点并形成清晰的结论。"
    }
  ],
  "multiBot": {
    "enabled": true
  },
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "YOUR_FEISHU_APP_ID",
      "appSecret": "YOUR_FEISHU_APP_SECRET"
    }
  }
}
```

#### 配置项说明：

-   **`bots` 列表**：定义了所有要启动的 Bot。
    -   `name`: Bot 在群聊中显示的名称，请尽量独特以方便区分。
    -   `model`: 该 Bot 使用的 LLM 模型。对于智谱，推荐使用 `glm-4.5-flash`。
    -   `apiKey`: 您为该 Bot 分配的专属 API Key。
    -   `persona`: Bot 的角色设定，这会影响它的发言风格和思考角度。
-   **`channels.feishu`**：飞书的连接配置。
    -   `enabled`: 必须设置为 `true`。
    -   `appId`: 填入您在步骤 4 中获取的 App ID。
    -   `appSecret`: 填入您在步骤 4 中获取的 App Secret。

您可以根据需要，在 `bots` 列表中添加更多使用不同 API Key（如 OpenAI, Claude 等）的 Bot。

---

## 6. 启动与使用

### 步骤 6.1: 运行启动脚本

我们为您准备了一个方便的 Windows 启动脚本 `start_bots.bat`。

回到您克隆代码的 `nanobot` 目录，双击运行 `start_bots.bat` 文件。

一个命令提示符窗口将会打开，如果一切顺利，您会看到类似以下的输出：

```
============================================
  nanobot Multi-Bot Group Chat Gateway
============================================

[INFO] Starting nanobot gateway...
[INFO] Config: C:\Users\YourUsername\.nanobot\config.json
[INFO] Press Ctrl+C to stop all bots.

🐈 Starting nanobot gateway in MULTI-BOT mode...
  Bots configured: 3
  [1] 分析师小智 (model: glm-4.5-flash)
  [2] 创意师小慧 (model: glm-4.5-flash)
  [3] 总结师小明 (model: glm-4.5-flash)
✓ 3 bots initialized
✓ Channels enabled: feishu
✓ Multi-bot gateway ready on port 18790
Bots will respond to group messages collaboratively.
```

**请保持此窗口运行**，关闭它会终止所有 Bot 服务。

### 步骤 6.2: 在飞书群聊中互动

现在，您可以去到您的飞书群聊，像和普通用户聊天一样发布任务或提出问题。

例如，您可以发送：

> 大家好，我们来讨论一下如何为一款新的咖啡产品制定营销策略。

稍等片刻，您将看到群里的 Bot 们开始根据自己的“人设”进行讨论和回复，例如：

> **【分析师小智】**: 制定营销策略前，我们首先需要明确目标市场（Target Audience）和核心卖点（USP）。建议先进行竞品分析，收集市场上主流咖啡品牌的价格、渠道和宣传方式数据。

> **【创意师小慧】**: 我们可以尝试一些跨界联名！比如和本地的书店合作推出“阅读伴侣”套餐，或者和健身房联名主打“能量补充”概念。还可以发起一个社交媒体挑战，比如 #我的咖啡拉花艺术#。

> **【总结师小明】**: 好的，总结一下。小智提出了数据驱动的分析路径，小慧提供了创新的营销点子。我们可以将两者结合：第一步，按小智的建议做市场调研；第二步，基于调研结果，从小慧的创意中筛选出最匹配目标用户的几个方案进行落地。

至此，您已成功部署并体验了 `nanobot` 多 Bot 协作平台！

---

## 7. 故障排查

-   **启动时提示 API Key 错误**：请检查 `config.json` 中的 `apiKey` 是否填写正确，并确保您的 API Key 仍然有效且有足够额度。
-   **飞书收不到消息**：
    1.  确认 `config.json` 中的 `appId` 和 `appSecret` 是否正确。
    2.  确认飞书后台的事件订阅中 `im.message.receive_v1` 是否已添加。
    3.  确认机器人是否已被邀请到群聊中。
-   **只有一个 Bot 回复**：检查 `config.json` 中 `bots` 列表是否正确配置了多个 Bot。

如果您遇到其他问题，请随时向我们反馈。
