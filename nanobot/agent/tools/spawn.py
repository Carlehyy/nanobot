"""
子Agent生成工具模块

提供创建后台子Agent的功能，用于处理复杂或耗时的任务。
"""

from typing import Any, TYPE_CHECKING

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """
    子Agent生成工具
    
    功能：生成一个子Agent在后台执行任务
    
    参数：
        task (str): 子Agent要完成的任务描述
        label (str): 可选，任务的简短标签（用于显示）
    
    工作原理：
        1. 主Agent调用spawn工具
        2. 创建一个新的子Agent实例
        3. 子Agent在后台异步执行任务
        4. 任务完成后，子Agent通过系统消息通知主Agent
        5. 主Agent将结果转发给用户
    
    特性：
        - 异步执行，不阻塞主Agent
        - 独立的上下文和工具集
        - 自动通知完成状态
        - 支持任务标签
    
    使用场景：
        - 复杂的数据分析任务
        - 耗时的文件处理
        - 批量操作
        - 定时监控任务
    
    使用示例：
        tool = SpawnTool(manager=subagent_manager)
        tool.set_context("telegram", "123456")
        await tool.execute(
            task="分析最近100个日志文件并生成报告",
            label="日志分析"
        )
    """
    
    def __init__(self, manager: "SubagentManager"):
        """
        初始化子Agent生成工具
        
        Args:
            manager: 子Agent管理器实例
        """
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """
        设置子Agent通知的来源上下文
        
        Args:
            channel: 渠道名称
            chat_id: 聊天ID
        
        说明：
            子Agent完成任务后，会向这个渠道和聊天ID发送通知
        """
        self._origin_channel = channel
        self._origin_chat_id = chat_id
    
    @property
    def name(self) -> str:
        return "spawn"
    
    @property
    def description(self) -> str:
        return (
            "生成一个子Agent在后台处理任务。"
            "用于可以独立运行的复杂或耗时任务。"
            "子Agent将完成任务并在完成时报告结果。"
        )
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "子Agent要完成的任务",
                },
                "label": {
                    "type": "string",
                    "description": "可选的任务简短标签（用于显示）",
                },
            },
            "required": ["task"],
        }
    
    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """
        执行子Agent生成
        
        Args:
            task: 任务描述
            label: 可选的任务标签
            **kwargs: 其他参数（忽略）
        
        Returns:
            子Agent启动确认消息
        
        流程：
            1. 调用SubagentManager的spawn方法
            2. 创建新的子Agent实例
            3. 在后台启动子Agent任务
            4. 返回启动确认消息给主Agent
        """
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
        )
