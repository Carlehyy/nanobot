"""
Multi-bot process manager for coordinating multiple independent bot processes.

Architecture (Process Isolation Mode):
- Each bot runs as a completely independent subprocess
- Each bot has its own Feishu application (separate identity in group chat)
- Each bot has its own LLM API key
- Bots share context naturally through Feishu group chat history
- The main process (Supervisor) monitors and auto-restarts crashed bots
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.schema import BotConfig, Config, MultiBotConfig


class BotProcessSupervisor:
    """
    Supervisor that manages multiple independent bot processes.
    
    Each bot runs as a separate `nanobot bot-worker` process with its own:
    - Feishu WebSocket connection (independent app identity)
    - LLM provider and API key
    - Persona and system prompt
    
    The supervisor handles:
    - Starting all bot processes
    - Monitoring process health
    - Auto-restarting crashed processes
    - Graceful shutdown of all processes
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.multi_bot_config = config.multi_bot
        self.processes: dict[str, subprocess.Popen] = {}  # bot_name -> process
        self._running = False
    
    def start_all(self) -> None:
        """Start all bot processes."""
        self._running = True
        
        for i, bot_config in enumerate(self.config.bots):
            if not bot_config.api_key:
                logger.warning(f"Bot '{bot_config.name}' has no API key, skipping")
                continue
            
            if not bot_config.feishu.app_id or not bot_config.feishu.app_secret:
                logger.warning(f"Bot '{bot_config.name}' has no Feishu credentials, skipping")
                continue
            
            self._start_bot_process(i, bot_config)
        
        logger.info(f"BotProcessSupervisor: {len(self.processes)} bot processes started")
    
    def _start_bot_process(self, index: int, bot_config: BotConfig) -> None:
        """Start a single bot as an independent subprocess."""
        # Serialize the bot config to pass via environment variable
        bot_config_json = json.dumps({
            "name": bot_config.name,
            "model": bot_config.model,
            "api_key": bot_config.api_key,
            "api_base": bot_config.api_base,
            "persona": bot_config.persona,
            "feishu": {
                "app_id": bot_config.feishu.app_id,
                "app_secret": bot_config.feishu.app_secret,
            },
        })
        
        # Build environment for the subprocess
        env = os.environ.copy()
        env["NANOBOT_BOT_CONFIG"] = bot_config_json
        env["NANOBOT_BOT_INDEX"] = str(index)
        env["NANOBOT_WORKSPACE"] = str(self.config.workspace_path)
        
        # Pass multi-bot settings
        env["NANOBOT_MULTI_BOT_REPLY_DELAY_MIN"] = str(self.multi_bot_config.reply_delay_min)
        env["NANOBOT_MULTI_BOT_REPLY_DELAY_MAX"] = str(self.multi_bot_config.reply_delay_max)
        env["NANOBOT_MULTI_BOT_MAX_ROUNDS"] = str(self.multi_bot_config.max_rounds_per_topic)
        
        # Pass tools config if available
        if self.config.tools.web.search.api_key:
            env["NANOBOT_BRAVE_API_KEY"] = self.config.tools.web.search.api_key
        
        # Start the subprocess
        cmd = [sys.executable, "-m", "nanobot", "bot-worker"]
        
        try:
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            self.processes[bot_config.name] = process
            logger.info(
                f"Started bot process: {bot_config.name} "
                f"(PID: {process.pid}, model: {bot_config.model})"
            )
        except Exception as e:
            logger.error(f"Failed to start bot process '{bot_config.name}': {e}")
    
    def monitor_and_restart(self) -> None:
        """
        Monitor all bot processes and restart any that have crashed.
        This is the main loop of the supervisor - runs until stopped.
        """
        while self._running:
            for i, bot_config in enumerate(self.config.bots):
                name = bot_config.name
                process = self.processes.get(name)
                
                if process is None:
                    continue
                
                # Check if process is still running
                retcode = process.poll()
                if retcode is not None:
                    # Process has exited
                    if self._running and self.multi_bot_config.auto_restart:
                        logger.warning(
                            f"Bot '{name}' exited with code {retcode}. "
                            f"Restarting in {self.multi_bot_config.restart_delay}s..."
                        )
                        time.sleep(self.multi_bot_config.restart_delay)
                        if self._running:  # Check again after sleep
                            self._start_bot_process(i, bot_config)
                    else:
                        logger.info(f"Bot '{name}' exited with code {retcode}")
            
            # Check every 2 seconds
            time.sleep(2)
    
    def stop_all(self) -> None:
        """Gracefully stop all bot processes."""
        self._running = False
        logger.info("Stopping all bot processes...")
        
        for name, process in self.processes.items():
            if process.poll() is None:  # Still running
                logger.info(f"Sending SIGTERM to bot '{name}' (PID: {process.pid})")
                try:
                    if sys.platform == "win32":
                        process.terminate()
                    else:
                        process.send_signal(signal.SIGTERM)
                except OSError:
                    pass
        
        # Wait for processes to exit gracefully (up to 10 seconds)
        deadline = time.time() + 10
        for name, process in self.processes.items():
            remaining = max(0, deadline - time.time())
            try:
                process.wait(timeout=remaining)
                logger.info(f"Bot '{name}' stopped gracefully")
            except subprocess.TimeoutExpired:
                logger.warning(f"Bot '{name}' did not stop gracefully, killing...")
                process.kill()
        
        self.processes.clear()
        logger.info("All bot processes stopped")
    
    def get_status(self) -> dict[str, Any]:
        """Get status of all bot processes."""
        status = {
            "mode": "multi-bot-process-isolation",
            "bot_count": len(self.processes),
            "auto_restart": self.multi_bot_config.auto_restart,
            "bots": [],
        }
        
        for bot_config in self.config.bots:
            name = bot_config.name
            process = self.processes.get(name)
            bot_status = {
                "name": name,
                "model": bot_config.model,
                "feishu_app_id": bot_config.feishu.app_id[:8] + "..." if bot_config.feishu.app_id else "N/A",
                "persona": (bot_config.persona[:50] + "...") if len(bot_config.persona) > 50 else bot_config.persona,
                "pid": process.pid if process and process.poll() is None else None,
                "running": process is not None and process.poll() is None,
            }
            status["bots"].append(bot_status)
        
        return status
