"""
子Agent管理模块：后台任务并行执行

子Agent是轻量级的Agent实例，运行在后台处理特定任务。
它们与主Agent共享LLM提供商，但有独立的上下文和专注的系统提示词。

子Agent的设计理念：
1. 专注性：每个子Agent只处理一个特定任务
2. 隔离性：独立的上下文，不访问主Agent的对话历史
3. 受限性：不能发送消息或生成新的子Agent（防止递归）
4. 异步性：真正的后台运行，不阻塞主Agent

典型使用场景：
- 长时间的数据分析
- 批量文件处理
- 定时监控任务
- 复杂的多步骤操作
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool


class SubagentManager:
    """
    子Agent管理器：管理后台任务的执行
    
    这个类负责：
    1. 生成子Agent（spawn）
    2. 管理子Agent的生命周期
    3. 收集子Agent的执行结果
    4. 通过消息总线通知主Agent
    
    子Agent与主Agent的区别：
    - 主Agent：处理用户对话，有完整的上下文和历史
    - 子Agent：处理单一任务，有专注的提示词，无对话历史
    
    子Agent的工具限制：
    - 可用：文件操作、Shell执行、Web搜索
    - 不可用：消息发送、生成子Agent（防止递归）
    
    属性:
        provider: LLM提供商
        workspace: 工作空间路径
        bus: 消息总线
        model: 使用的模型名称
        brave_api_key: Brave搜索API密钥
        exec_config: Shell工具的执行配置
        _running_tasks: 正在运行的子Agent任务字典
    
    示例:
        >>> manager = SubagentManager(provider, workspace, bus)
        >>> status = await manager.spawn(
        ...     task="分析最近一周的日志文件",
        ...     label="日志分析",
        ...     origin_channel="telegram",
        ...     origin_chat_id="123456"
        ... )
        >>> print(status)
        "Subagent [日志分析] started (id: a1b2c3d4). I'll notify you when it completes."
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
    ):
        """
        初始化子Agent管理器
        
        参数:
            provider: LLM提供商实例
            workspace: 工作空间路径
            bus: 消息总线实例
            model: 模型名称（可选）
            brave_api_key: Brave搜索API密钥（可选）
            exec_config: Shell工具的执行配置（可选）
        """
        from nanobot.config.schema import ExecToolConfig
        
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        
        # 正在运行的任务字典：task_id -> asyncio.Task
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
    
    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """
        生成一个子Agent来执行后台任务
        
        这个方法会：
        1. 生成唯一的任务ID
        2. 创建异步后台任务
        3. 注册任务到运行字典
        4. 设置完成后的清理回调
        5. 立即返回状态消息（不等待任务完成）
        
        参数:
            task: 任务描述（会作为子Agent的用户消息）
            label: 人类可读的任务标签（可选，用于显示）
            origin_channel: 结果通知的目标渠道
            origin_chat_id: 结果通知的目标聊天ID
        
        返回:
            str: 状态消息，告知用户子Agent已启动
        
        示例:
            >>> status = await manager.spawn(
            ...     task="搜索并总结最新的AI新闻",
            ...     label="AI新闻总结"
            ... )
            >>> print(status)
            "Subagent [AI新闻总结] started (id: a1b2c3d4). I'll notify you when it completes."
        
        注意:
            - 任务ID是UUID的前8位，用于跟踪和日志
            - 如果没有提供label，会使用任务描述的前30个字符
            - 任务完成后会通过消息总线发送通知
        """
        # 生成唯一的任务ID（UUID的前8位）
        task_id = str(uuid.uuid4())[:8]
        
        # 生成显示标签（如果没有提供，使用任务描述的前30个字符）
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        
        # 记录原始来源（用于结果通知）
        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }
        
        # 创建后台任务（异步执行，不阻塞）
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        
        # 设置完成后的清理回调（从运行字典中移除）
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))
        
        logger.info(f"Spawned subagent [{task_id}]: {display_label}")
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."
    
    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """
        执行子Agent任务并通知结果
        
        这是子Agent的主执行逻辑，流程：
        1. 构建子Agent的工具集（受限版本）
        2. 构建子Agent的系统提示词
        3. 运行Agent循环（最多15次迭代）
        4. 收集最终结果
        5. 通过消息总线通知主Agent
        
        参数:
            task_id: 任务ID
            task: 任务描述
            label: 任务标签
            origin: 原始来源信息（channel和chat_id）
        
        异常处理:
            任何异常都会被捕获，并作为错误结果通知主Agent
        """
        logger.info(f"Subagent [{task_id}] starting task: {label}")
        
        try:
            # 1. 构建子Agent的工具集（不包含message和spawn工具）
            tools = ToolRegistry()
            tools.register(ReadFileTool())  # 读取文件
            tools.register(WriteFileTool())  # 写入文件
            tools.register(ListDirTool())  # 列出目录
            tools.register(ExecTool(  # 执行Shell命令
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.exec_config.restrict_to_workspace,
            ))
            tools.register(WebSearchTool(api_key=self.brave_api_key))  # Web搜索
            tools.register(WebFetchTool())  # 抓取网页
            
            # 2. 构建子Agent的系统提示词（专注于单一任务）
            system_prompt = self._build_subagent_prompt(task)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            
            # 3. 运行Agent循环（限制15次迭代）
            max_iterations = 15
            iteration = 0
            final_result: str | None = None
            
            while iteration < max_iterations:
                iteration += 1
                
                # 调用LLM
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                )
                
                # 处理工具调用
                if response.has_tool_calls:
                    # 添加助手消息（包含工具调用）
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # 执行所有工具
                    for tool_call in response.tool_calls:
                        logger.debug(f"Subagent [{task_id}] executing: {tool_call.name}")
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    # 没有工具调用，得到最终结果
                    final_result = response.content
                    break
            
            # 如果达到最大迭代次数仍未完成
            if final_result is None:
                final_result = "Task completed but no final response was generated."
            
            # 4. 通知成功结果
            logger.info(f"Subagent [{task_id}] completed successfully")
            await self._announce_result(task_id, label, task, final_result, origin, "ok")
            
        except Exception as e:
            # 5. 通知错误结果
            error_msg = f"Error: {str(e)}"
            logger.error(f"Subagent [{task_id}] failed: {e}")
            await self._announce_result(task_id, label, task, error_msg, origin, "error")
    
    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
    ) -> None:
        """
        通过消息总线通知主Agent子Agent的执行结果
        
        这个方法会：
        1. 构造通知消息（包含任务、结果和状态）
        2. 封装为系统消息
        3. 发送到消息总线的入站队列
        4. 主Agent会处理这个系统消息并生成用户友好的摘要
        
        参数:
            task_id: 任务ID
            label: 任务标签
            task: 任务描述
            result: 执行结果
            origin: 原始来源信息
            status: 状态（"ok"或"error"）
        
        注意:
            - 通知消息的channel是"system"，表示这是系统内部消息
            - chat_id格式为"channel:chat_id"，用于路由回复
            - 通知内容包含指导主Agent如何处理结果的说明
        """
        status_text = "completed successfully" if status == "ok" else "failed"
        
        # 构造通知内容（包含指导主Agent的说明）
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""
        
        # 封装为系统消息
        msg = InboundMessage(
            channel="system",  # 系统通道
            sender_id="subagent",  # 发送者是子Agent
            chat_id=f"{origin['channel']}:{origin['chat_id']}",  # 路由信息
            content=announce_content,
        )
        
        # 发送到消息总线
        await self.bus.publish_inbound(msg)
        logger.debug(f"Subagent [{task_id}] announced result to {origin['channel']}:{origin['chat_id']}")
    
    def _build_subagent_prompt(self, task: str) -> str:
        """
        构建子Agent的系统提示词
        
        子Agent的提示词与主Agent不同，更加专注和受限：
        1. 明确任务目标
        2. 强调专注性（只做这一件事）
        3. 列出可用和不可用的工具
        4. 说明结果会被报告给主Agent
        
        参数:
            task: 任务描述
        
        返回:
            str: 子Agent的系统提示词
        
        设计理念:
            - 专注：只完成指定任务，不做其他事情
            - 受限：不能发送消息或生成子Agent
            - 简洁：提示词简短明了，避免干扰
        """
        return f"""# Subagent

You are a subagent spawned by the main agent to complete a specific task.

## Your Task
{task}

## Rules
1. Stay focused - complete only the assigned task, nothing else
2. Your final response will be reported back to the main agent
3. Do not initiate conversations or take on side tasks
4. Be concise but informative in your findings

## What You Can Do
- Read and write files in the workspace
- Execute shell commands
- Search the web and fetch web pages
- Complete the task thoroughly

## What You Cannot Do
- Send messages directly to users (no message tool available)
- Spawn other subagents
- Access the main agent's conversation history

## Workspace
Your workspace is at: {self.workspace}

When you have completed the task, provide a clear summary of your findings or actions."""
    
    def get_running_count(self) -> int:
        """
        获取当前正在运行的子Agent数量
        
        返回:
            int: 正在运行的子Agent数量
        
        示例:
            >>> count = manager.get_running_count()
            >>> print(f"当前有 {count} 个子Agent正在运行")
        """
        return len(self._running_tasks)
