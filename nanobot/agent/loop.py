"""
Agent循环模块：Agent的核心处理引擎

这是nanobot的心脏，实现了经典的Agent循环模式：
1. 从消息总线接收消息
2. 构建包含历史记录、记忆和技能的上下文
3. 调用LLM获取响应
4. 执行LLM返回的工具调用
5. 将响应发送回消息总线

核心流程：
    用户消息 → 构建上下文 → 调用LLM → 执行工具 → 再次调用LLM → ... → 返回最终响应
"""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager


class AgentLoop:
    """
    Agent循环：核心处理引擎
    
    这个类实现了Agent的主要处理逻辑，负责：
    1. 从消息总线接收入站消息
    2. 构建完整的上下文（系统提示词、历史记录、记忆、技能）
    3. 调用LLM获取响应
    4. 执行LLM返回的工具调用
    5. 将最终响应发送回消息总线
    
    Agent循环的核心思想是：
    - LLM决定是否需要调用工具
    - 如果需要，执行工具并将结果反馈给LLM
    - 重复这个过程，直到LLM给出最终答案
    - 设置最大迭代次数防止无限循环
    
    属性:
        bus: 消息总线，用于接收和发送消息
        provider: LLM提供商，用于调用大语言模型
        workspace: 工作空间路径
        model: 使用的模型名称
        max_iterations: 最大迭代次数，防止无限循环
        brave_api_key: Brave搜索API密钥（可选）
        exec_config: Shell工具的执行配置
        context: 上下文构建器
        sessions: 会话管理器
        tools: 工具注册表
        subagents: 子Agent管理器
    
    示例:
        >>> bus = MessageBus()
        >>> provider = LiteLLMProvider(...)
        >>> workspace = Path("~/.nanobot/workspace")
        >>> loop = AgentLoop(bus, provider, workspace)
        >>> await loop.run()  # 启动Agent循环
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
    ):
        """
        初始化Agent循环
        
        参数:
            bus: 消息总线实例
            provider: LLM提供商实例
            workspace: 工作空间路径
            model: 模型名称，如果为None则使用provider的默认模型
            max_iterations: 最大迭代次数，默认20次
            brave_api_key: Brave搜索API密钥（可选）
            exec_config: Shell工具的执行配置（可选）
        """
        from nanobot.config.schema import ExecToolConfig
        
        # 核心组件
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        
        # 初始化各个管理器
        self.context = ContextBuilder(workspace)  # 上下文构建器
        self.sessions = SessionManager(workspace)  # 会话管理器
        self.tools = ToolRegistry()  # 工具注册表
        self.subagents = SubagentManager(  # 子Agent管理器
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )
        
        # 运行状态标志
        self._running = False
        
        # 注册默认工具集
        self._register_default_tools()
    
    def _register_default_tools(self) -> None:
        """
        注册默认工具集
        
        这个方法在初始化时被调用，注册所有内置工具：
        - 文件操作工具：读取、写入、编辑、列出目录
        - Shell工具：执行命令
        - Web工具：搜索、抓取网页
        - 消息工具：发送消息到指定渠道
        - 子Agent工具：生成后台任务
        """
        # 文件操作工具
        self.tools.register(ReadFileTool())  # 读取文件
        self.tools.register(WriteFileTool())  # 写入文件
        self.tools.register(EditFileTool())  # 编辑文件
        self.tools.register(ListDirTool())  # 列出目录
        
        # Shell命令执行工具
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),  # 工作目录
            timeout=self.exec_config.timeout,  # 超时时间
            restrict_to_workspace=self.exec_config.restrict_to_workspace,  # 是否限制在工作空间内
        ))
        
        # Web工具
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))  # Web搜索
        self.tools.register(WebFetchTool())  # 抓取网页内容
        
        # 消息工具（用于发送消息到特定渠道）
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)
        
        # 子Agent生成工具（用于后台任务）
        spawn_tool = SpawnTool(manager=self.subagents)
        self.tools.register(spawn_tool)
    
    async def run(self) -> None:
        """
        运行Agent循环，持续处理来自消息总线的消息
        
        这是Agent的主循环，会一直运行直到调用stop()方法。
        循环逻辑：
        1. 等待消息总线的入站消息（带1秒超时）
        2. 处理消息并生成响应
        3. 将响应发送到出站队列
        4. 如果处理出错，发送错误消息
        5. 重复以上步骤
        
        异常处理：
        - asyncio.TimeoutError: 超时则继续等待下一条消息
        - Exception: 捕获处理异常并发送错误响应给用户
        """
        self._running = True
        logger.info("Agent loop started")  # 记录启动日志
        
        while self._running:
            try:
                # 等待下一条消息（带1秒超时，避免阻塞stop()调用）
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # 处理消息
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # 发送错误响应给用户
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                # 超时是正常的，继续循环
                continue
    
    def stop(self) -> None:
        """
        停止Agent循环
        
        设置运行标志为False，Agent循环会在下一次迭代时退出。
        """
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        处理单条入站消息
        
        这是消息处理的核心方法，实现了完整的Agent循环逻辑：
        1. 获取或创建会话
        2. 更新工具上下文（channel和chat_id）
        3. 构建包含历史记录的完整上下文
        4. 进入Agent循环：
           a. 调用LLM
           b. 如果有工具调用，执行工具并将结果添加到消息历史
           c. 重复直到LLM不再调用工具或达到最大迭代次数
        5. 保存会话历史
        6. 返回最终响应
        
        参数:
            msg: 入站消息对象
        
        返回:
            OutboundMessage: 出站消息对象，如果不需要响应则返回None
        
        注意:
            - 系统消息（channel="system"）会被路由到_process_system_message
            - 每个channel:chat_id维护独立的会话历史
            - 工具上下文会在每次处理前更新，确保工具知道当前的渠道和聊天ID
        """
        # 处理系统消息（子Agent的通知消息）
        # chat_id包含原始的"channel:chat_id"用于路由回复
        if msg.channel == "system":
            return await self._process_system_message(msg)
        
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")
        
        # 获取或创建会话（每个channel:chat_id有独立的会话）
        session = self.sessions.get_or_create(msg.session_key)
        
        # 更新工具上下文（让工具知道当前的渠道和聊天ID）
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)
        
        # 构建初始消息列表（包含系统提示词、历史记录和当前消息）
        messages = self.context.build_messages(
            history=session.get_history(),  # 获取格式化的历史记录
            current_message=msg.content,  # 当前用户消息
            media=msg.media if msg.media else None,  # 可选的媒体文件（如图片）
        )
        
        # Agent循环：LLM调用 → 工具执行 → LLM调用 → ...
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            # 调用LLM获取响应
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),  # 提供所有可用工具的定义
                model=self.model
            )
            
            # 处理工具调用
            if response.has_tool_calls:
                # 将助手的消息（包含工具调用）添加到历史
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # 必须是JSON字符串
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                # 执行所有工具调用
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    
                    # 执行工具并获取结果
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    
                    # 将工具执行结果添加到消息历史
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # LLM没有调用工具，说明已经得到最终答案
                final_content = response.content
                break
        
        # 如果达到最大迭代次数仍未得到答案，使用默认消息
        if final_content is None:
            final_content = "I've completed processing but have no response to give."
        
        # 保存对话历史到会话
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        # 返回出站消息
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        处理系统消息（例如子Agent的通知消息）
        
        系统消息是子Agent完成任务后发送的通知，需要特殊处理：
        1. chat_id字段包含"原始渠道:原始聊天ID"，用于路由响应
        2. 使用原始会话的上下文，保持对话连贯性
        3. 处理流程与普通消息类似，但会在历史中标记为系统消息
        
        参数:
            msg: 系统消息对象
        
        返回:
            OutboundMessage: 路由到原始渠道的出站消息
        
        注意:
            chat_id格式为"channel:chat_id"，例如"telegram:123456"
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # 解析原始来源（格式："channel:chat_id"）
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # 回退方案
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # 使用原始会话的上下文
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # 更新工具上下文到原始渠道
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        # 构建包含通知内容的消息列表
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content
        )
        
        # Agent循环（处理子Agent的通知）
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # 保存到会话（在历史中标记为系统消息）
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        # 返回到原始渠道
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(self, content: str, session_key: str = "cli:direct") -> str:
        """
        直接处理消息（用于CLI使用）
        
        这是一个便捷方法，用于在CLI模式下直接处理消息，
        无需通过消息总线。
        
        参数:
            content: 消息内容
            session_key: 会话标识符，默认为"cli:direct"
        
        返回:
            str: Agent的响应内容
        
        示例:
            >>> loop = AgentLoop(...)
            >>> response = await loop.process_direct("Hello, what's 2+2?")
            >>> print(response)
            "2+2 equals 4."
        """
        # 构造入站消息
        msg = InboundMessage(
            channel="cli",
            sender_id="user",
            chat_id="direct",
            content=content
        )
        
        # 处理消息并返回响应内容
        response = await self._process_message(msg)
        return response.content if response else ""
