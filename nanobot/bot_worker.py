"""
Independent bot worker process.

Each bot worker has its own:
- Feishu WebSocket connection (independent app identity)
- LLM provider and API key
- Persona and system prompt
- Message processing loop

Free Discussion Mode:
  After a human sends a message and bots reply, each bot starts a
  "discussion polling" loop that periodically fetches the latest group
  chat history via Feishu API. If new messages from other bots are
  detected, the bot generates a follow-up response, creating a natural
  multi-agent discussion.

  User commands:
  - "闭麦" / "mute"   — Bots stop free discussion
  - "开麦" / "unmute"  — Bots resume free discussion
"""

import asyncio
import json
import os
import platform
import random
import signal
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


# ============================================================================
# Feishu Group Chat History Fetcher
# ============================================================================


class FeishuHistoryFetcher:
    """Fetches recent group chat history from Feishu API."""

    def __init__(self, client: Any):
        self._client = client

    def fetch_recent_messages(self, chat_id: str, count: int = 20) -> list[dict]:
        """
        Fetch recent messages from a Feishu group chat.

        Returns list of dicts: {"role": "user"|"assistant", "content": str, "msg_id": str, "sender_type": str}
        """
        try:
            from lark_oapi.api.im.v1 import ListMessageRequest

            request = (
                ListMessageRequest.builder()
                .container_id_type("chat")
                .container_id(chat_id)
                .page_size(count)
                .build()
            )

            response = self._client.im.v1.message.list(request)

            if not response.success():
                logger.debug(f"Failed to fetch chat history: {response.code} {response.msg}")
                return []

            messages: list[dict] = []
            items = response.data.items if response.data and response.data.items else []

            for item in reversed(items):
                try:
                    # Determine sender type
                    sender_type_raw = ""
                    if item.sender and item.sender.sender_type:
                        sender_type_raw = item.sender.sender_type

                    # Skip system messages (empty sender_type)
                    if not sender_type_raw or item.msg_type == "system":
                        continue

                    is_bot = sender_type_raw == "app"
                    role = "assistant" if is_bot else "user"

                    if item.msg_type == "text":
                        content_data = json.loads(item.body.content) if item.body and item.body.content else {}
                        content = content_data.get("text", "")
                    else:
                        content = f"[{item.msg_type}]"

                    if content:
                        messages.append({
                            "role": role,
                            "content": content,
                            "msg_id": item.message_id or "",
                            "sender_type": sender_type_raw,
                        })
                except Exception:
                    continue

            return messages

        except Exception as e:
            logger.debug(f"Error fetching chat history: {e}")
            return []


# ============================================================================
# LLM Worker Thread
# ============================================================================


class LLMWorkerThread:
    """Runs LLM calls in a dedicated thread with its own event loop."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro) -> asyncio.Future:
        if self._loop is None:
            raise RuntimeError("LLM worker thread not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)


# ============================================================================
# Mute / Unmute helpers
# ============================================================================

MUTE_COMMANDS = {"闭麦", "全体闭麦", "mute", "mute all", "安静", "别说了", "停"}
UNMUTE_COMMANDS = {"开麦", "unmute", "继续", "说吧", "开始讨论"}


def is_mute_command(text: str) -> bool:
    return text.strip().lower() in MUTE_COMMANDS


def is_unmute_command(text: str) -> bool:
    return text.strip().lower() in UNMUTE_COMMANDS


# ============================================================================
# Bot Worker
# ============================================================================


class BotWorker:
    """
    A single independent bot worker process.

    After replying to a human message, the bot enters a *discussion polling*
    phase: it periodically fetches the latest chat history via Feishu API,
    detects new messages from other bots, and generates follow-up responses
    to create a natural multi-agent discussion.
    """

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def __init__(self):
        self.bot_config = self._load_bot_config()
        self.workspace = Path(os.environ.get("NANOBOT_WORKSPACE", "~/.nanobot/workspace")).expanduser()

        # Timing
        self.reply_delay_min = float(os.environ.get("NANOBOT_MULTI_BOT_REPLY_DELAY_MIN", "2.0"))
        self.reply_delay_max = float(os.environ.get("NANOBOT_MULTI_BOT_REPLY_DELAY_MAX", "5.0"))
        self.max_discussion_rounds = int(os.environ.get("NANOBOT_MULTI_BOT_MAX_ROUNDS", "3"))
        self.discussion_poll_interval = float(os.environ.get("NANOBOT_DISCUSSION_POLL_INTERVAL", "10.0"))
        self.discussion_timeout = float(os.environ.get("NANOBOT_DISCUSSION_TIMEOUT", "120.0"))

        # State
        self._running = False
        self._muted = False
        self._client: Any = None
        self._history_fetcher: FeishuHistoryFetcher | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._provider = None
        self._llm_worker = LLMWorkerThread()

        # Discussion state per chat
        self._discussion_rounds: dict[str, int] = {}  # chat_id -> rounds replied in current discussion
        self._last_seen_msg_id: dict[str, str] = {}   # chat_id -> last msg_id we've seen
        self._discussion_active: dict[str, bool] = {}  # chat_id -> whether polling is active

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_bot_config(self) -> dict:
        config_json = os.environ.get("NANOBOT_BOT_CONFIG", "{}")
        try:
            return json.loads(config_json)
        except json.JSONDecodeError:
            logger.error("Failed to parse NANOBOT_BOT_CONFIG")
            sys.exit(1)

    def _init_provider(self) -> None:
        from nanobot.providers.litellm_provider import LiteLLMProvider
        self._provider = LiteLLMProvider(
            api_key=self.bot_config.get("api_key", ""),
            api_base=self.bot_config.get("api_base"),
            default_model=self.bot_config.get("model", "glm-4.5-flash"),
        )

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(self, chat_id: str) -> str:
        name = self.bot_config.get("name", "nanobot")
        persona = self.bot_config.get("persona", "")

        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        system_info = platform.system()
        runtime = f"{'macOS' if system_info == 'Darwin' else system_info} {platform.machine()}, Python {platform.python_version()}"

        persona_block = f"\n## 你的角色设定\n{persona}\n" if persona else ""
        mute_status = "已闭麦，仅回复人类消息" if self._muted else "开麦中，可自由参与讨论"

        return (
            f"# {name}\n\n"
            f"你是 **{name}**，一个在飞书群聊中参与协作的 AI 助手。\n"
            f"{persona_block}\n"
            f"## 当前时间\n{now}\n\n"
            f"## 运行环境\n{runtime}\n\n"
            f"## 状态\n{mute_status}\n\n"
            f"## 群聊协作规则\n\n"
            f"你正在一个**多 AI 协作群聊**中，群里有多个 AI Bot 和人类用户。\n\n"
            f"1. 你的名字是 **{name}**。回复时无需重复添加名字前缀（系统会自动添加）。\n"
            f"2. 当人类用户发消息时，你**必须积极回复**，给出你独特的见解和观点。\n"
            f"3. 看到其他 Bot 的发言时，请自然地参与讨论，提出不同观点或补充。\n"
            f"4. 始终保持你的角色特点，展现你的专业性。\n"
            f"5. 回复简洁有力，每次不超过200字。\n"
            f"6. 不要重复其他 Bot 已说过的内容，提供新的价值。\n"
            f"7. 可以直接称呼其他 Bot 的名字，引用他们的观点进行讨论。\n\n"
            f"## 当前会话\nChat ID: {chat_id}\n"
        )

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    async def _call_llm(self, chat_id: str, extra_user_msg: str | None = None, must_reply: bool = False) -> str | None:
        """
        Build context from chat history + system prompt, call LLM, return response text.
        Returns None if the bot decides to skip (only allowed when must_reply=False).
        """
        name = self.bot_config.get("name", "nanobot")
        model = self.bot_config.get("model", "glm-4.5-flash")

        system_prompt = self._build_system_prompt(chat_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]

        # Fetch chat history
        if self._history_fetcher and chat_id.startswith("oc_"):
            history = self._history_fetcher.fetch_recent_messages(chat_id, count=30)
            if history:
                for h in history:
                    messages.append({"role": h["role"], "content": h["content"]})
                logger.debug(f"Bot [{name}] loaded {len(history)} messages from chat history")

        if extra_user_msg:
            messages.append({"role": "user", "content": extra_user_msg})

        try:
            response = await self._provider.chat(messages=messages, model=model)
            content = response.content
            if not content:
                return None
            if "[SKIP]" in content and not must_reply:
                logger.debug(f"Bot [{name}] chose to skip")
                return None
            elif "[SKIP]" in content and must_reply:
                # Must reply mode - strip SKIP and re-call if content is only SKIP
                content = content.replace("[SKIP]", "").strip()
                if not content:
                    logger.debug(f"Bot [{name}] tried to skip but must_reply=True, retrying...")
                    # Retry with explicit instruction
                    retry_msg = f"请你以 {name} 的身份针对群聊中的最新话题给出你的独特观点和见解，必须回复，不能跳过。"
                    messages_retry = messages + [{"role": "user", "content": retry_msg}]
                    try:
                        response2 = await self._provider.chat(messages=messages_retry, model=model)
                        content = response2.content or ""
                        content = content.replace("[SKIP]", "").strip()
                        if not content:
                            return None
                    except Exception:
                        return None
            # Add name prefix
            prefix = f"【{name}】"
            if not content.startswith(prefix):
                content = f"{prefix}: {content}"
            return content
        except Exception as e:
            logger.error(f"Bot [{name}] LLM error: {e}")
            return None

    # ------------------------------------------------------------------
    # Feishu send
    # ------------------------------------------------------------------

    def _send_feishu_message_sync(self, chat_id: str, content: str) -> None:
        if not self._client:
            return
        try:
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            receive_id_type = "chat_id" if chat_id.startswith("oc_") else "open_id"
            msg_content = json.dumps({"text": content})

            request = (
                CreateMessageRequest.builder()
                .receive_id_type(receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(chat_id)
                    .msg_type("text")
                    .content(msg_content)
                    .build()
                )
                .build()
            )
            response = self._client.im.v1.message.create(request)
            if not response.success():
                logger.error(f"Failed to send message: code={response.code}, msg={response.msg}")
            else:
                logger.debug(f"Message sent to {chat_id}")
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    # ------------------------------------------------------------------
    # Discussion polling loop
    # ------------------------------------------------------------------

    async def _discussion_poll_loop(self, chat_id: str, trigger_human_msg_id: str = ""):
        """
        After the bot replies to a human message, periodically poll the chat
        history to detect new messages from other bots and generate follow-up
        responses.
        
        Args:
            chat_id: The chat to poll
            trigger_human_msg_id: The message_id of the human message that triggered
                this discussion. This message will be ignored when checking for
                "new human messages" to avoid premature exit.
        """
        name = self.bot_config.get("name", "nanobot")
        start_time = time.time()

        logger.info(f"Bot [{name}] starting discussion poll for {chat_id} (trigger_msg: {trigger_human_msg_id[:20]}...)")

        while (
            self._running
            and not self._muted
            and self._discussion_active.get(chat_id, False)
            and self._discussion_rounds.get(chat_id, 0) < self.max_discussion_rounds
            and (time.time() - start_time) < self.discussion_timeout
        ):
            # Wait before polling
            await asyncio.sleep(self.discussion_poll_interval)

            if self._muted or not self._discussion_active.get(chat_id, False):
                break

            # Fetch latest messages
            if not self._history_fetcher:
                break

            history = self._history_fetcher.fetch_recent_messages(chat_id, count=10)
            if not history:
                continue

            # Find the last message
            last_msg = history[-1]
            last_msg_id = last_msg.get("msg_id", "")
            last_content = last_msg.get("content", "")
            last_sender_type = last_msg.get("sender_type", "user")

            # Check if there's a new message we haven't seen
            prev_seen = self._last_seen_msg_id.get(chat_id, "")
            if last_msg_id == prev_seen:
                # No new messages, keep waiting
                continue

            # Update last seen
            self._last_seen_msg_id[chat_id] = last_msg_id

            # If the last message is from a human, check if it's a NEW human message
            if last_sender_type == "user":
                if is_mute_command(last_content):
                    self._muted = True
                    logger.info(f"Bot [{name}] muted by new user command")
                    break
                if is_unmute_command(last_content):
                    # Reset discussion
                    self._discussion_rounds[chat_id] = 0
                    continue
                # Check if this is the SAME human message that triggered the discussion
                if last_msg_id == trigger_human_msg_id:
                    # Same message, no new bot replies yet, keep waiting
                    logger.debug(f"Bot [{name}] last msg is still the trigger human msg, keep polling...")
                    continue
                # Truly new human message — stop this poll loop; the event handler will start a new one
                logger.debug(f"Bot [{name}] NEW human message detected (different from trigger), ending poll loop")
                break

            # The last message is from a bot — check if it's our own
            if f"【{name}】" in last_content:
                # Our own message, skip
                continue

            # Another bot posted something new — decide whether to reply
            current_round = self._discussion_rounds.get(chat_id, 0)
            if current_round >= self.max_discussion_rounds:
                logger.debug(f"Bot [{name}] max discussion rounds reached")
                break

            # Probabilistic reply: decreasing chance each round
            reply_prob = max(0.3, 0.85 - current_round * 0.2)
            if random.random() > reply_prob:
                logger.debug(f"Bot [{name}] randomly skipping this round (prob={reply_prob:.0%})")
                continue

            # Add a natural delay before replying
            delay = random.uniform(3.0, 8.0)
            logger.info(f"Bot [{name}] will reply to other bot's message in {delay:.1f}s")
            await asyncio.sleep(delay)

            # Generate response
            prompt = (
                f"请你以 {name} 的身份继续参与群聊讨论。"
                f"阅读上面的聊天记录，特别是其他Bot的最新发言，给出你的回应。"
                f"简洁回复，不超过150字。如果没有新内容要补充，回复 [SKIP] 。"
            )
            response = await self._call_llm(chat_id, extra_user_msg=prompt)

            if response:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._send_feishu_message_sync, chat_id, response)
                self._discussion_rounds[chat_id] = current_round + 1
                logger.info(f"Bot [{name}] discussion reply (round {current_round + 1}): {response[:80]}...")
            else:
                logger.debug(f"Bot [{name}] no response generated, ending discussion")
                break

        self._discussion_active[chat_id] = False
        logger.info(f"Bot [{name}] discussion poll ended for {chat_id} (rounds: {self._discussion_rounds.get(chat_id, 0)})")

    # ------------------------------------------------------------------
    # Feishu message event handler
    # ------------------------------------------------------------------

    def _on_message_handler(self, data: Any) -> None:
        """Handler for incoming Feishu messages (only human messages arrive here)."""
        name = self.bot_config.get("name", "nanobot")

        try:
            event = data.event
            message = event.message
            sender = event.sender

            # Dedup
            message_id = message.message_id
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            sender_type = sender.sender_type
            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type

            # Parse content
            if msg_type == "text":
                try:
                    content = json.loads(message.content).get("text", "")
                except json.JSONDecodeError:
                    content = message.content or ""
            else:
                content = f"[{msg_type}]"

            if not content:
                return

            reply_to = chat_id if chat_type == "group" else sender_id

            # Bot messages won't arrive via event, but just in case
            if sender_type == "app":
                return

            logger.info(f"Bot [{name}] received HUMAN message: {content[:60]}...")

            # Handle mute/unmute
            if is_mute_command(content):
                self._muted = True
                self._discussion_active[chat_id] = False
                logger.info(f"Bot [{name}] MUTED")
                self._send_feishu_message_sync(reply_to, f"【{name}】: 收到，已闭麦")
                return

            if is_unmute_command(content):
                self._muted = False
                self._discussion_rounds[chat_id] = 0
                logger.info(f"Bot [{name}] UNMUTED")
                self._send_feishu_message_sync(reply_to, f"【{name}】: 收到，已开麦，随时准备参与讨论!")
                return

            # Reset discussion state for this chat
            self._discussion_rounds[chat_id] = 0

            # Save the trigger message_id for discussion polling
            trigger_msg_id = message_id

            # Dispatch to LLM worker
            async def process_and_reply():
                # Random delay
                delay = random.uniform(self.reply_delay_min, self.reply_delay_max)
                await asyncio.sleep(delay)

                # Generate response - must reply to human messages
                response = await self._call_llm(reply_to, must_reply=True)

                if response:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._send_feishu_message_sync, reply_to, response)
                    logger.info(f"Bot [{name}] replied: {response[:80]}...")

                    # Update last seen msg_id to current latest
                    if self._history_fetcher and reply_to.startswith("oc_"):
                        latest = self._history_fetcher.fetch_recent_messages(reply_to, count=1)
                        if latest:
                            self._last_seen_msg_id[reply_to] = latest[-1].get("msg_id", "")

                    # Start discussion polling if not muted and in group chat
                    if not self._muted and chat_type == "group":
                        self._discussion_active[reply_to] = True
                        # Small delay before starting poll to let other bots reply first
                        await asyncio.sleep(8.0)
                        await self._discussion_poll_loop(reply_to, trigger_human_msg_id=trigger_msg_id)

            self._llm_worker.submit(process_and_reply())

        except Exception as e:
            logger.error(f"Bot [{name}] error handling message: {e}")

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def run(self) -> None:
        name = self.bot_config.get("name", "nanobot")
        feishu_config = self.bot_config.get("feishu", {})
        app_id = feishu_config.get("app_id", "")
        app_secret = feishu_config.get("app_secret", "")

        if not app_id or not app_secret:
            logger.error(f"Bot [{name}] missing Feishu credentials")
            sys.exit(1)

        logger.info(f"Bot [{name}] starting (model: {self.bot_config.get('model', 'unknown')})")

        self._init_provider()
        self._llm_worker.start()
        logger.info(f"Bot [{name}] LLM worker thread started")

        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        except ImportError:
            logger.error("Feishu SDK not installed. Run: pip install lark-oapi")
            sys.exit(1)

        self._running = True

        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        self._history_fetcher = FeishuHistoryFetcher(self._client)

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_handler)
            .build()
        )

        ws_client = lark.ws.Client(
            app_id,
            app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        def handle_signal(signum, frame):
            logger.info(f"Bot [{name}] received signal {signum}, shutting down...")
            self._running = False
            self._llm_worker.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        logger.info(f"Bot [{name}] connecting to Feishu via WebSocket...")
        logger.info(f"Bot [{name}] ready (free discussion: {'OFF - muted' if self._muted else 'ON'})")

        try:
            ws_client.start()
        except Exception as e:
            logger.error(f"Bot [{name}] WebSocket error: {e}")
        finally:
            self._llm_worker.stop()
            logger.info(f"Bot [{name}] stopped")


def run_worker():
    """Entry point for the bot-worker command."""
    worker = BotWorker()
    worker.run()
