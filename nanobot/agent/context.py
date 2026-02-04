"""
上下文构建模块：组装Agent的提示词和消息

这个模块负责构建Agent所需的完整上下文，包括：
1. 核心身份和系统提示词
2. 引导文件（AGENTS.md、SOUL.md等）
3. 长期记忆（从MEMORY.md加载）
4. 技能系统（可用技能的摘要和详情）
5. 对话历史
6. 多模态内容（文本+图片）

上下文构建是Agent能力的关键，一个好的上下文能让Agent：
- 理解自己的身份和能力
- 访问长期记忆和知识
- 使用正确的工具和技能
- 保持对话的连贯性
"""

import base64
import mimetypes
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader


class ContextBuilder:
    """
    上下文构建器：组装Agent的提示词
    
    这个类负责将各种信息源组装成一个完整的上下文，供LLM使用。
    上下文的组成部分：
    1. 核心身份：Agent的基本信息、当前时间、工作空间路径
    2. 引导文件：从workspace加载的配置文件（AGENTS.md、SOUL.md等）
    3. 记忆：从MEMORY.md加载的长期记忆
    4. 技能：可用技能的摘要（Agent可按需加载详情）
    5. 对话历史：之前的对话记录
    
    设计理念：
    - 渐进式加载：不是一次性加载所有内容，而是按需加载
    - 技能摘要：只显示技能列表，Agent通过read_file工具按需加载详情
    - 多模态支持：支持文本和图片的混合输入
    
    属性:
        workspace: 工作空间路径
        memory: 记忆存储实例
        skills: 技能加载器实例
    
    示例:
        >>> workspace = Path("~/.nanobot/workspace")
        >>> builder = ContextBuilder(workspace)
        >>> messages = builder.build_messages(
        ...     history=[],
        ...     current_message="Hello!"
        ... )
    """
    
    # 引导文件列表（按顺序加载）
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def __init__(self, workspace: Path):
        """
        初始化上下文构建器
        
        参数:
            workspace: 工作空间路径
        """
        self.workspace = workspace
        self.memory = MemoryStore(workspace)  # 记忆存储
        self.skills = SkillsLoader(workspace)  # 技能加载器
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        构建系统提示词
        
        系统提示词是Agent的"操作手册"，包含：
        1. 核心身份：Agent是谁，有什么能力
        2. 引导文件：行为指南、个性定义等
        3. 记忆上下文：长期记忆和知识
        4. 技能系统：
           - 总是加载的技能：完整内容
           - 可用技能：仅摘要，Agent可通过read_file按需加载
        
        参数:
            skill_names: 要包含的技能名称列表（可选）
        
        返回:
            str: 完整的系统提示词
        
        注意:
            各部分之间用"---"分隔，便于阅读和调试
        """
        parts = []
        
        # 1. 核心身份（必需）
        parts.append(self._get_identity())
        
        # 2. 引导文件（如果存在）
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # 3. 记忆上下文（如果有记忆）
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # 4. 技能系统 - 渐进式加载
        # 4.1 总是加载的技能：包含完整内容
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        
        # 4.2 可用技能：仅显示摘要（Agent使用read_file工具按需加载）
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")
        
        # 用分隔符连接各部分
        return "\n\n---\n\n".join(parts)
    
    def _get_identity(self) -> str:
        """
        获取核心身份部分
        
        这是系统提示词的第一部分，包含：
        - Agent的名称和基本介绍
        - 可用工具列表
        - 当前时间
        - 工作空间路径
        - 重要的使用说明
        
        返回:
            str: 核心身份文本
        
        注意:
            - 当前时间会实时更新
            - 工作空间路径会被解析为绝对路径
        """
        from datetime import datetime
        
        # 获取当前时间（格式：2024-01-15 14:30 (Monday)）
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        
        # 获取工作空间的绝对路径
        workspace_path = str(self.workspace.expanduser().resolve())
        
        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant. You have access to tools that allow you to:
- Read, write, and edit files
- Execute shell commands
- Search the web and fetch web pages
- Send messages to users on chat channels
- Spawn subagents for complex background tasks

## Current Time
{now}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

IMPORTANT: When responding to direct questions or conversations, reply directly with your text response.
Only use the 'message' tool when you need to send a message to a specific chat channel (like WhatsApp).
For normal conversation, just respond with text - do not call the message tool.

Always be helpful, accurate, and concise. When using tools, explain what you're doing.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""
    
    def _load_bootstrap_files(self) -> str:
        """
        加载所有引导文件
        
        引导文件是放在workspace根目录的配置文件，用于定制Agent的行为：
        - AGENTS.md: Agent的行为指南
        - SOUL.md: Agent的个性定义
        - USER.md: 用户信息
        - TOOLS.md: 工具使用说明
        - IDENTITY.md: 身份定制
        
        返回:
            str: 所有引导文件的内容（如果没有则返回空字符串）
        
        注意:
            文件按BOOTSTRAP_FILES列表的顺序加载
        """
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""
    
    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        构建完整的消息列表供LLM调用
        
        这是上下文构建的主入口，返回符合OpenAI格式的消息列表：
        [
            {"role": "system", "content": "系统提示词..."},
            {"role": "user", "content": "历史消息1"},
            {"role": "assistant", "content": "历史回复1"},
            ...
            {"role": "user", "content": "当前消息（可能包含图片）"}
        ]
        
        参数:
            history: 之前的对话消息列表
            current_message: 当前用户消息
            skill_names: 要包含的技能名称列表（可选）
            media: 本地媒体文件路径列表（可选，如图片）
        
        返回:
            list[dict]: OpenAI格式的消息列表
        
        注意:
            - 系统提示词总是第一条消息
            - 如果提供了media，会将图片编码为base64并嵌入消息
        """
        messages = []

        # 1. 系统提示词（必需）
        system_prompt = self.build_system_prompt(skill_names)
        messages.append({"role": "system", "content": system_prompt})

        # 2. 历史对话
        messages.extend(history)

        # 3. 当前消息（可能包含图片附件）
        user_content = self._build_user_content(current_message, media)
        messages.append({"role": "user", "content": user_content})

        return messages

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """
        构建用户消息内容（支持多模态）
        
        如果没有媒体文件，直接返回文本。
        如果有媒体文件（如图片），将其编码为base64并嵌入消息。
        
        参数:
            text: 文本内容
            media: 媒体文件路径列表（可选）
        
        返回:
            str | list: 如果没有媒体则返回字符串，否则返回多模态内容列表
        
        多模态格式示例:
            [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}},
                {"type": "text", "text": "这是什么？"}
            ]
        
        注意:
            - 只处理图片类型的文件（通过MIME类型判断）
            - 图片会被编码为base64 data URL
        """
        if not media:
            return text
        
        # 处理媒体文件（主要是图片）
        images = []
        for path in media:
            p = Path(path)
            mime, _ = mimetypes.guess_type(path)
            
            # 只处理存在的图片文件
            if not p.is_file() or not mime or not mime.startswith("image/"):
                continue
            
            # 读取文件并编码为base64
            b64 = base64.b64encode(p.read_bytes()).decode()
            
            # 构造data URL
            images.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}
            })
        
        # 如果没有有效的图片，返回纯文本
        if not images:
            return text
        
        # 返回多模态内容：图片 + 文本
        return images + [{"type": "text", "text": text}]
    
    def add_tool_result(
        self,
        messages: list[dict[str, Any]],
        tool_call_id: str,
        tool_name: str,
        result: str
    ) -> list[dict[str, Any]]:
        """
        将工具执行结果添加到消息列表
        
        当Agent调用工具后，需要将执行结果反馈给LLM，
        这样LLM才能基于结果继续推理。
        
        参数:
            messages: 当前消息列表
            tool_call_id: 工具调用的ID（用于关联）
            tool_name: 工具名称
            result: 工具执行结果（字符串）
        
        返回:
            list[dict]: 更新后的消息列表
        
        消息格式:
            {
                "role": "tool",
                "tool_call_id": "call_abc123",
                "name": "read_file",
                "content": "文件内容..."
            }
        """
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": tool_name,
            "content": result
        })
        return messages
    
    def add_assistant_message(
        self,
        messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """
        将助手消息添加到消息列表
        
        助手消息有两种情况：
        1. 普通回复：只有content
        2. 工具调用：有content和tool_calls
        
        参数:
            messages: 当前消息列表
            content: 消息内容（可能为空）
            tool_calls: 工具调用列表（可选）
        
        返回:
            list[dict]: 更新后的消息列表
        
        消息格式（工具调用）:
            {
                "role": "assistant",
                "content": "让我查看一下文件...",
                "tool_calls": [
                    {
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": "{\"path\": \"/path/to/file\"}"
                        }
                    }
                ]
            }
        """
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        
        # 如果有工具调用，添加到消息中
        if tool_calls:
            msg["tool_calls"] = tool_calls
        
        messages.append(msg)
        return messages
