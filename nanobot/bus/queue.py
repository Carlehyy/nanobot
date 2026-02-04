"""
消息总线模块：解耦的异步消息路由

消息总线是nanobot架构的核心组件，实现了渠道和Agent之间的解耦通信。

架构模式：发布-订阅（Pub-Sub）
    渠道 → 发布入站消息 → 消息总线 → Agent消费
    Agent → 发布出站消息 → 消息总线 → 渠道订阅并消费

优势：
1. 解耦：渠道和Agent不直接依赖，通过消息总线通信
2. 异步：使用asyncio.Queue实现非阻塞通信
3. 多渠道：支持多个渠道同时工作（Telegram、WhatsApp、CLI等）
4. 容错：单个渠道异常不影响其他渠道
5. 可扩展：轻松添加新的渠道类型

消息流向：
    用户 → Telegram → InboundQueue → Agent → OutboundQueue → Telegram → 用户
    用户 → WhatsApp → InboundQueue → Agent → OutboundQueue → WhatsApp → 用户
    用户 → CLI → InboundQueue → Agent → OutboundQueue → CLI → 用户
"""

import asyncio
from typing import Callable, Awaitable

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """
    异步消息总线：解耦渠道和Agent的通信
    
    消息总线维护两个异步队列：
    1. 入站队列（inbound）：渠道发布，Agent消费
    2. 出站队列（outbound）：Agent发布，渠道消费
    
    工作流程：
    1. 渠道接收用户消息，封装为InboundMessage，发布到入站队列
    2. Agent从入站队列消费消息，处理后生成响应
    3. Agent将响应封装为OutboundMessage，发布到出站队列
    4. 消息总线的dispatcher将出站消息分发给订阅的渠道
    5. 渠道将响应发送给用户
    
    属性:
        inbound: 入站消息队列（渠道 → Agent）
        outbound: 出站消息队列（Agent → 渠道）
        _outbound_subscribers: 出站消息订阅者字典（channel → callbacks）
        _running: dispatcher运行标志
    
    示例:
        >>> bus = MessageBus()
        >>> 
        >>> # 渠道发布消息
        >>> await bus.publish_inbound(InboundMessage(...))
        >>> 
        >>> # Agent消费消息
        >>> msg = await bus.consume_inbound()
        >>> 
        >>> # Agent发布响应
        >>> await bus.publish_outbound(OutboundMessage(...))
        >>> 
        >>> # 启动dispatcher（后台任务）
        >>> asyncio.create_task(bus.dispatch_outbound())
    """
    
    def __init__(self):
        """
        初始化消息总线
        
        创建两个异步队列和订阅者字典。
        """
        # 入站队列：渠道 → Agent
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        
        # 出站队列：Agent → 渠道
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()
        
        # 出站消息订阅者：channel名称 → 回调函数列表
        self._outbound_subscribers: dict[str, list[Callable[[OutboundMessage], Awaitable[None]]]] = {}
        
        # dispatcher运行标志
        self._running = False
    
    async def publish_inbound(self, msg: InboundMessage) -> None:
        """
        发布入站消息（渠道调用）
        
        渠道接收到用户消息后，封装为InboundMessage并调用此方法，
        将消息放入入站队列，等待Agent消费。
        
        参数:
            msg: 入站消息对象
        
        示例:
            >>> msg = InboundMessage(
            ...     channel="telegram",
            ...     sender_id="123456",
            ...     chat_id="123456",
            ...     content="Hello!"
            ... )
            >>> await bus.publish_inbound(msg)
        """
        await self.inbound.put(msg)
    
    async def consume_inbound(self) -> InboundMessage:
        """
        消费入站消息（Agent调用）
        
        Agent调用此方法从入站队列获取下一条消息。
        如果队列为空，会阻塞等待直到有新消息。
        
        返回:
            InboundMessage: 入站消息对象
        
        示例:
            >>> msg = await bus.consume_inbound()
            >>> print(f"收到来自 {msg.channel} 的消息: {msg.content}")
        
        注意:
            这是一个阻塞操作，会等待直到有消息可用
        """
        return await self.inbound.get()
    
    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """
        发布出站消息（Agent调用）
        
        Agent处理完消息后，封装为OutboundMessage并调用此方法，
        将响应放入出站队列，等待dispatcher分发给渠道。
        
        参数:
            msg: 出站消息对象
        
        示例:
            >>> msg = OutboundMessage(
            ...     channel="telegram",
            ...     chat_id="123456",
            ...     content="Hello! How can I help you?"
            ... )
            >>> await bus.publish_outbound(msg)
        """
        await self.outbound.put(msg)
    
    async def consume_outbound(self) -> OutboundMessage:
        """
        消费出站消息（内部使用）
        
        从出站队列获取下一条消息。
        通常由dispatcher调用，不建议外部直接使用。
        
        返回:
            OutboundMessage: 出站消息对象
        
        注意:
            这是一个阻塞操作，会等待直到有消息可用
        """
        return await self.outbound.get()
    
    def subscribe_outbound(
        self, 
        channel: str, 
        callback: Callable[[OutboundMessage], Awaitable[None]]
    ) -> None:
        """
        订阅出站消息（渠道调用）
        
        渠道调用此方法注册回调函数，当有发往该渠道的消息时，
        dispatcher会调用回调函数。
        
        参数:
            channel: 渠道名称（如"telegram"、"whatsapp"）
            callback: 异步回调函数，接收OutboundMessage参数
        
        示例:
            >>> async def handle_message(msg: OutboundMessage):
            ...     print(f"发送消息到 {msg.chat_id}: {msg.content}")
            ...     # 实际发送逻辑...
            >>> 
            >>> bus.subscribe_outbound("telegram", handle_message)
        
        注意:
            - 一个渠道可以注册多个回调函数
            - 回调函数必须是异步函数（async def）
        """
        if channel not in self._outbound_subscribers:
            self._outbound_subscribers[channel] = []
        self._outbound_subscribers[channel].append(callback)
    
    async def dispatch_outbound(self) -> None:
        """
        分发出站消息到订阅的渠道（后台任务）
        
        这是消息总线的核心调度循环，负责：
        1. 从出站队列获取消息（带1秒超时）
        2. 根据消息的channel字段查找订阅者
        3. 调用所有订阅者的回调函数
        4. 处理回调异常（不影响其他订阅者）
        
        这个方法应该作为后台任务运行：
            asyncio.create_task(bus.dispatch_outbound())
        
        异常处理:
            - asyncio.TimeoutError: 超时则继续等待下一条消息
            - Exception: 捕获回调异常并记录日志，不影响其他订阅者
        
        示例:
            >>> # 启动dispatcher
            >>> task = asyncio.create_task(bus.dispatch_outbound())
            >>> 
            >>> # 停止dispatcher
            >>> bus.stop()
            >>> await task
        """
        self._running = True
        
        while self._running:
            try:
                # 等待下一条出站消息（带1秒超时）
                msg = await asyncio.wait_for(self.outbound.get(), timeout=1.0)
                
                # 查找该渠道的订阅者
                subscribers = self._outbound_subscribers.get(msg.channel, [])
                
                # 调用所有订阅者的回调函数
                for callback in subscribers:
                    try:
                        await callback(msg)
                    except Exception as e:
                        # 捕获并记录异常，不影响其他订阅者
                        logger.error(f"Error dispatching to {msg.channel}: {e}")
            except asyncio.TimeoutError:
                # 超时是正常的，继续循环
                continue
    
    def stop(self) -> None:
        """
        停止dispatcher循环
        
        设置运行标志为False，dispatcher会在下一次迭代时退出。
        
        示例:
            >>> bus.stop()
        """
        self._running = False
    
    @property
    def inbound_size(self) -> int:
        """
        获取入站队列中待处理的消息数量
        
        返回:
            int: 待处理的入站消息数量
        
        示例:
            >>> print(f"入站队列有 {bus.inbound_size} 条待处理消息")
        """
        return self.inbound.qsize()
    
    @property
    def outbound_size(self) -> int:
        """
        获取出站队列中待分发的消息数量
        
        返回:
            int: 待分发的出站消息数量
        
        示例:
            >>> print(f"出站队列有 {bus.outbound_size} 条待分发消息")
        """
        return self.outbound.qsize()
