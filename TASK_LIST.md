
# nanobot 改造任务清单

## 目标

基于 `nanobot` 现有代码，实现支持多 Bot 在同一个飞书群聊中协同工作的能力。每个 Bot 使用独立的 LLM API Key，能够接收群聊消息并参与讨论，最终将改造后的代码和使用文档推送到 GitHub 的 `chat-bot` 分支。

## 核心改造点

当前架构为“单 Agent 对多渠道”模式，需改造为“多 Agent 对单渠道（飞书群聊）”模式。

## 任务分解

| 序号 | 任务模块 | 任务项 | 详细说明 |
| :--- | :--- | :--- | :--- |
| 1 | **配置系统** | 重新设计 `config.json` 结构 | - 将原有的 `agents` 和 `providers` 配置合并，改为定义一个 `bots` 列表。<br>- 每个 `bot` 对象包含 `name`, `model`, `apiKey`, `apiBase` (可选), 和 `persona` (可选) 字段，用于定义一个独立的 Bot 实例。 |
| 2 | | 更新配置加载逻辑 | - 修改 `config/schema.py` 以匹配新的 `bots` 列表结构。<br>- 修改 `config/loader.py` 以正确解析新的配置文件。 |
| 3 | **核心网关** | 改造 `gateway` 启动命令 | - 修改 `cli/commands.py` 中的 `gateway` 函数。<br>- 启动时不再创建单个 `AgentLoop`，而是遍历 `config.json` 中的 `bots` 列表，为每个 Bot 创建一个独立的 `AgentLoop` 实例。 |
| 4 | | 实现多 Agent 实例化 | - 每个 `AgentLoop` 需使用其专属的 `model`, `apiKey`, `apiBase` 和 `persona` 进行初始化。 |
| 5 | **消息总线** | 实现消息广播机制 | - 当 `FeishuChannel` 收到一条群消息后，该消息需要被所有 Bot 实例接收。<br>- 改造 `AgentLoop` 的主循环，使其能从一个共享的、可广播的队列中获取消息，而不是像现在这样直接消费 `MessageBus` 的 `inbound` 队列。 |
| 6 | **Agent 身份** | 注入 Bot 专属身份 | - 修改 `agent/context.py` 中的 `ContextBuilder`。<br>- 在构建系统提示（System Prompt）时，将 Bot 的 `name` 和 `persona` 注入，使其拥有独特的身份认知。 |
| 7 | | 强化群聊上下文感知 | - 在 System Prompt 中明确指示 Bot，它正在一个多 Agent 协作的群聊环境中，需要注意识别其他 Bot 的发言。 |
| 8 | **代码实现** | 编写 `MultiBotManager` | - 创建一个新的管理器 `nanobot/bot_manager.py`，负责加载配置、创建和管理所有的 Bot 实例。<br>- `gateway` 命令将通过这个管理器来启动和停止所有 Bot。 |
| 9 | | 修改 `FeishuChannel` | - 确保飞书群聊消息能被正确地推送到新的广播机制中。 |
| 10 | | 修改 `AgentLoop` | - 调整 `AgentLoop` 以适应新的多 Bot 架构，特别是消息处理和会话管理部分。 |
| 11 | **本地验证** | 编写启动脚本 | - 创建一个 `run_bots.sh` 脚本，用于方便地启动多个 Bot 实例进行本地测试。 |
| 12 | | 对话与协作测试 | - 在模拟的飞书环境中，发送任务，验证：<br>  1. 所有 Bot 是否都能收到消息。<br>  2. 每个 Bot 是否使用其指定的模型和 API Key 进行响应。<br>  3. Bot 之间是否能进行有效的互动。 |
| 13 | **文档编写** | 撰写用户操作指南 | - 创建 `USER_GUIDE.md`，详细说明：<br>  1. 如何配置 `config.json` 来添加多个 Bot。<br>  2. 如何获取飞书 App ID 和 App Secret。<br>  3. 如何启动所有 Bot 并将它们接入飞书群聊。<br>  4. 如何在群聊中与 Bot 互动。 |
| 14 | **代码提交** | 配置 Git 和 GitHub 密钥 | - 使用提供的 GitHub 密钥配置 Git。 |
| 15 | | 创建并推送新分支 | - 创建 `chat-bot` 分支。<br>- 将所有修改后的代码和新文档提交到该分支。 |

---
