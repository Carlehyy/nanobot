"""Multi-bot manager for coordinating multiple bot instances in a group chat."""

import asyncio
import random
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import BotConfig, Config, MultiBotConfig
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.session.manager import SessionManager


class BotInstance:
    """
    A single bot instance within the multi-bot group chat.
    
    Each BotInstance has its own LLM provider, persona, and session,
    but shares the same message bus and feishu channel.
    """
    
    def __init__(
        self,
        bot_config: BotConfig,
        multi_bot_config: MultiBotConfig,
        workspace: "Path",
        bus: MessageBus,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
    ):
        from pathlib import Path
        from nanobot.config.schema import ExecToolConfig
        
        self.bot_config = bot_config
        self.multi_bot_config = multi_bot_config
        self.workspace = workspace
        self.bus = bus
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        
        # Create dedicated provider for this bot
        self.provider = LiteLLMProvider(
            api_key=bot_config.api_key,
            api_base=bot_config.api_base,
            default_model=bot_config.model,
        )
        
        # Create dedicated context builder with persona injection
        self.context = ContextBuilder(workspace)
        
        # Use a dedicated session namespace for this bot
        self.sessions = SessionManager(workspace)
        
        # Create tools
        self.tools = ToolRegistry()
        self._register_tools()
        
        # Track reply counts per topic to avoid infinite loops
        self._topic_reply_counts: dict[str, int] = {}
        
        self._running = False
    
    def _register_tools(self) -> None:
        """Register tools available to this bot."""
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(EditFileTool())
        self.tools.register(ListDirTool())
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
    
    def _build_system_prompt(self, channel: str, chat_id: str) -> str:
        """Build a system prompt with multi-bot group chat context and persona."""
        import platform
        from datetime import datetime
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        persona_section = ""
        if self.bot_config.persona:
            persona_section = f"""
## 你的角色设定
{self.bot_config.persona}
"""
        
        return f"""# {self.bot_config.name}

你是 **{self.bot_config.name}**，一个在飞书群聊中参与协作的 AI 助手。
{persona_section}
## 当前时间
{now}

## 运行环境
{runtime}

## 工作空间
你的工作空间位于: {workspace_path}

## 群聊协作规则

你正在一个**多 AI 协作群聊**环境中。群里有多个 AI Bot 和人类用户。请遵守以下规则：

1. **身份意识**：你的名字是 **{self.bot_config.name}**。在回复时，请始终以你的名字开头，格式为 `【{self.bot_config.name}】: `，这样群里的其他人可以识别你的发言。
2. **协作精神**：认真阅读群里其他 Bot 和用户的消息。如果其他 Bot 已经给出了很好的回答，你可以表示赞同并补充，而不是重复相同的内容。
3. **角色扮演**：如果你有特定的角色设定，请始终保持你的角色特点来回答问题。
4. **简洁高效**：群聊中的回复应当简洁有力，避免过于冗长。重点突出你的独特观点或贡献。
5. **尊重他人**：对其他 Bot 和用户的观点保持尊重，即使你有不同意见，也要礼貌地表达。
6. **避免重复**：如果你发现其他 Bot 已经充分回答了问题，你可以选择简短地表示赞同，或者从不同角度补充。
7. **直接回复**：直接用文字回复，不要调用 message 工具。

## 当前会话
Channel: {channel}
Chat ID: {chat_id}
"""
    
    async def process_message(
        self,
        msg: InboundMessage,
        group_history: list[dict[str, Any]],
    ) -> str | None:
        """
        Process an inbound message and generate a response.
        
        Args:
            msg: The inbound message from the group chat.
            group_history: Recent group chat history (shared across all bots).
        
        Returns:
            The bot's response text, or None if it decides not to reply.
        """
        import json
        
        # Check reply count for this topic to avoid infinite loops
        topic_key = f"{msg.chat_id}:{msg.content[:50]}"
        current_count = self._topic_reply_counts.get(topic_key, 0)
        if current_count >= self.multi_bot_config.max_rounds_per_topic:
            logger.debug(f"Bot [{self.bot_config.name}] skipping - max rounds reached for topic")
            return None
        
        # Build messages
        system_prompt = self._build_system_prompt(msg.channel, msg.chat_id)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]
        
        # Add group history for context
        messages.extend(group_history)
        
        # Add current message
        messages.append({"role": "user", "content": msg.content})
        
        # Call LLM
        try:
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.bot_config.model,
            )
            
            # Handle tool calls (limited iterations)
            iteration = 0
            max_iterations = 10
            
            while response.has_tool_calls and iteration < max_iterations:
                iteration += 1
                
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
                messages.append({
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": tool_call_dicts,
                })
                
                for tool_call in response.tool_calls:
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result,
                    })
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=self.tools.get_definitions(),
                    model=self.bot_config.model,
                )
            
            final_content = response.content
            if final_content:
                # Ensure the bot name prefix is present
                name_prefix = f"【{self.bot_config.name}】"
                if not final_content.startswith(name_prefix):
                    final_content = f"{name_prefix}: {final_content}"
                
                # Update reply count
                self._topic_reply_counts[topic_key] = current_count + 1
                
                # Clean up old topic counts (keep last 100)
                if len(self._topic_reply_counts) > 100:
                    keys = list(self._topic_reply_counts.keys())
                    for k in keys[:len(keys) - 50]:
                        self._topic_reply_counts.pop(k, None)
            
            return final_content
            
        except Exception as e:
            logger.error(f"Bot [{self.bot_config.name}] error processing message: {e}")
            return None


class MultiBotManager:
    """
    Manages multiple bot instances for group chat collaboration.
    
    Responsibilities:
    - Create and manage BotInstance objects from config
    - Broadcast incoming messages to all bots
    - Coordinate bot responses with staggered delays
    - Maintain shared group chat history
    """
    
    def __init__(self, config: Config, bus: MessageBus):
        self.config = config
        self.bus = bus
        self.bots: list[BotInstance] = []
        self._running = False
        self._group_history: list[dict[str, Any]] = []
        self._max_history = 50  # Keep last 50 messages in shared history
        
        self._init_bots()
    
    def _init_bots(self) -> None:
        """Initialize bot instances from config."""
        for i, bot_config in enumerate(self.config.bots):
            if not bot_config.api_key:
                logger.warning(f"Bot '{bot_config.name}' has no API key, skipping")
                continue
            
            bot = BotInstance(
                bot_config=bot_config,
                multi_bot_config=self.config.multi_bot,
                workspace=self.config.workspace_path,
                bus=self.bus,
                brave_api_key=self.config.tools.web.search.api_key or None,
                exec_config=self.config.tools.exec,
            )
            self.bots.append(bot)
            logger.info(f"Initialized bot: {bot_config.name} (model: {bot_config.model})")
        
        logger.info(f"MultiBotManager: {len(self.bots)} bots initialized")
    
    async def run(self) -> None:
        """
        Main loop: consume inbound messages and broadcast to all bots.
        """
        self._running = True
        logger.info("MultiBotManager started - waiting for messages")
        
        while self._running:
            try:
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0,
                )
                
                # Skip bot's own messages to avoid infinite loops
                sender_type = msg.metadata.get("sender_type", "")
                if sender_type == "bot":
                    logger.debug(f"Skipping bot message from {msg.sender_id}")
                    continue
                
                # Add user message to shared group history
                self._add_to_history("user", msg.content, msg.sender_id)
                
                # Process message with all bots concurrently
                await self._broadcast_to_bots(msg)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"MultiBotManager error: {e}")
    
    async def _broadcast_to_bots(self, msg: InboundMessage) -> None:
        """
        Broadcast a message to all bots and collect their responses.
        Bots reply with staggered delays to simulate natural conversation.
        """
        # Create tasks for all bots
        tasks = []
        for bot in self.bots:
            tasks.append(self._get_bot_response(bot, msg))
        
        # Gather all responses
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Send responses with staggered delays
        for bot, response in zip(self.bots, responses):
            if isinstance(response, Exception):
                logger.error(f"Bot [{bot.bot_config.name}] raised exception: {response}")
                continue
            
            if response is None:
                continue
            
            # Add random delay to simulate natural conversation
            delay = random.uniform(
                self.config.multi_bot.reply_delay_min,
                self.config.multi_bot.reply_delay_max,
            )
            await asyncio.sleep(delay)
            
            # Send response to the channel
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=response,
            ))
            
            # Add bot response to shared group history
            self._add_to_history("assistant", response, bot.bot_config.name)
    
    async def _get_bot_response(
        self, bot: BotInstance, msg: InboundMessage
    ) -> str | None:
        """Get a response from a single bot."""
        try:
            return await bot.process_message(
                msg=msg,
                group_history=list(self._group_history),  # Pass a copy
            )
        except Exception as e:
            logger.error(f"Bot [{bot.bot_config.name}] failed: {e}")
            return None
    
    def _add_to_history(self, role: str, content: str, sender: str = "") -> None:
        """Add a message to the shared group history."""
        if sender and role == "user":
            # Prefix user messages with sender info for context
            entry = {"role": "user", "content": f"[{sender}]: {content}"}
        elif role == "assistant":
            # Bot messages already have name prefix from BotInstance
            entry = {"role": "assistant", "content": content}
        else:
            entry = {"role": role, "content": content}
        
        self._group_history.append(entry)
        
        # Trim history
        if len(self._group_history) > self._max_history:
            self._group_history = self._group_history[-self._max_history:]
    
    def stop(self) -> None:
        """Stop the multi-bot manager."""
        self._running = False
        logger.info("MultiBotManager stopped")
    
    def get_status(self) -> dict[str, Any]:
        """Get status of all bots."""
        return {
            "mode": "multi-bot",
            "bot_count": len(self.bots),
            "bots": [
                {
                    "name": bot.bot_config.name,
                    "model": bot.bot_config.model,
                    "persona": bot.bot_config.persona[:50] + "..." if len(bot.bot_config.persona) > 50 else bot.bot_config.persona,
                }
                for bot in self.bots
            ],
        }
