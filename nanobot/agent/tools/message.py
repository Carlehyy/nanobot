"""
消息工具模块

提供向用户发送消息的功能，允许Agent主动与用户通信。
"""

from typing import Any, Callable, Awaitable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage


class MessageTool(Tool):
    """
    消息发送工具
    
    功能：向聊天渠道的用户发送消息
    
    参数：
        content (str): 要发送的消息内容
        channel (str): 可选，目标渠道（telegram、discord等）
        chat_id (str): 可选，目标聊天/用户ID
    
    特性：
        - 支持多渠道发送
        - 可设置默认渠道和聊天ID
        - 通过回调函数发送消息
    
    使用场景：
        - Agent需要主动通知用户
        - 发送中间进度更新
        - 发送后台任务完成通知
    
    使用示例：
        tool = MessageTool(send_callback=bus.send)
        tool.set_context("telegram", "123456")
        await tool.execute("任务完成！")
    """
    
    def __init__(
        self, 
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = ""
    ):
        """
        初始化消息工具
        
        Args:
            send_callback: 发送消息的回调函数
            default_channel: 默认渠道
            default_chat_id: 默认聊天ID
        """
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
    
    def set_context(self, channel: str, chat_id: str) -> None:
        """
        设置当前消息上下文
        
        Args:
            channel: 渠道名称
            chat_id: 聊天ID
        """
        self._default_channel = channel
        self._default_chat_id = chat_id
    
    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """
        设置发送消息的回调函数
        
        Args:
            callback: 异步回调函数，接收OutboundMessage参数
        """
        self._send_callback = callback
    
    @property
    def name(self) -> str:
        return "message"
    
    @property
    def description(self) -> str:
        return "向用户发送消息。当你想要与用户沟通时使用此工具。"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要发送的消息内容"
                },
                "channel": {
                    "type": "string",
                    "description": "可选：目标渠道（telegram、discord等）"
                },
                "chat_id": {
                    "type": "string",
                    "description": "可选：目标聊天/用户ID"
                }
            },
            "required": ["content"]
        }
    
    async def execute(
        self, 
        content: str, 
        channel: str | None = None, 
        chat_id: str | None = None,
        **kwargs: Any
    ) -> str:
        """
        执行消息发送
        
        Args:
            content: 消息内容
            channel: 目标渠道（可选，使用默认值）
            chat_id: 目标聊天ID（可选，使用默认值）
            **kwargs: 其他参数（忽略）
        
        Returns:
            成功消息或错误信息
        """
        # 使用提供的值或默认值
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        
        # 验证必要参数
        if not channel or not chat_id:
            return "错误：未指定目标渠道/聊天"
        
        if not self._send_callback:
            return "错误：消息发送未配置"
        
        # 构造出站消息
        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content
        )
        
        try:
            # 调用回调函数发送消息
            await self._send_callback(msg)
            return f"消息已发送到 {channel}:{chat_id}"
        except Exception as e:
            return f"发送消息时出错：{str(e)}"
