"""
Shell执行工具模块

提供在系统中执行Shell命令的能力，包含安全防护机制。

安全特性：
- 命令黑名单（阻止危险命令如rm -rf）
- 命令白名单（可选）
- 工作目录限制
- 执行超时控制
- 输出长度限制
"""

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """
    Shell命令执行工具
    
    功能：执行Shell命令并返回输出
    
    参数：
        timeout (int): 命令执行超时时间（秒），默认60秒
        working_dir (str | None): 默认工作目录
        deny_patterns (list[str] | None): 危险命令的正则表达式黑名单
        allow_patterns (list[str] | None): 允许的命令正则表达式白名单
        restrict_to_workspace (bool): 是否限制只能在工作目录内执行
    
    安全机制：
        1. 黑名单：阻止rm -rf、format、shutdown等危险命令
        2. 白名单：如果设置，只允许匹配的命令
        3. 工作目录限制：防止访问工作目录外的文件
        4. 超时控制：防止命令长时间运行
        5. 输出截断：限制输出长度为10000字符
    
    使用示例：
        tool = ExecTool(timeout=30, restrict_to_workspace=True)
        result = await tool.execute("ls -la")
    """
    
    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
    ):
        """
        初始化Shell执行工具
        
        Args:
            timeout: 命令执行超时时间（秒）
            working_dir: 默认工作目录
            deny_patterns: 危险命令的正则表达式列表
            allow_patterns: 允许的命令正则表达式列表
            restrict_to_workspace: 是否限制在工作目录内
        """
        self.timeout = timeout
        self.working_dir = working_dir
        
        # 默认的危险命令黑名单
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q (Windows)
            r"\brmdir\s+/s\b",               # rmdir /s (Windows)
            r"\b(format|mkfs|diskpart)\b",   # 磁盘格式化操作
            r"\bdd\s+if=",                   # dd命令（可能覆盖磁盘）
            r">\s*/dev/sd",                  # 写入磁盘设备
            r"\b(shutdown|reboot|poweroff)\b",  # 系统电源操作
            r":\(\)\s*\{.*\};\s*:",          # fork炸弹
        ]
        
        self.allow_patterns = allow_patterns or []
        self.restrict_to_workspace = restrict_to_workspace
    
    @property
    def name(self) -> str:
        return "exec"
    
    @property
    def description(self) -> str:
        return "执行Shell命令并返回输出。请谨慎使用。"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的Shell命令"
                },
                "working_dir": {
                    "type": "string",
                    "description": "可选的命令工作目录"
                }
            },
            "required": ["command"]
        }
    
    async def execute(self, command: str, working_dir: str | None = None, **kwargs: Any) -> str:
        """
        执行Shell命令
        
        Args:
            command: 要执行的Shell命令
            working_dir: 可选的工作目录（覆盖默认值）
            **kwargs: 其他参数（忽略）
        
        Returns:
            命令输出（stdout和stderr），或错误信息
        
        流程：
            1. 确定工作目录
            2. 安全检查（黑名单、白名单、路径限制）
            3. 执行命令（带超时控制）
            4. 收集输出（stdout和stderr）
            5. 处理退出码
            6. 截断过长输出
        """
        # 确定工作目录：参数 > 实例默认 > 当前目录
        cwd = working_dir or self.working_dir or os.getcwd()
        
        # 安全检查
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error
        
        try:
            # 创建子进程执行命令
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            
            try:
                # 等待命令完成（带超时）
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )
            except asyncio.TimeoutError:
                # 超时则杀死进程
                process.kill()
                return f"错误：命令执行超时（{self.timeout}秒）"
            
            # 收集输出
            output_parts = []
            
            # 添加标准输出
            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))
            
            # 添加标准错误（如果有内容）
            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")
            
            # 添加退出码（如果非0）
            if process.returncode != 0:
                output_parts.append(f"\n退出码: {process.returncode}")
            
            result = "\n".join(output_parts) if output_parts else "(无输出)"
            
            # 截断过长输出
            max_len = 10000
            if len(result) > max_len:
                result = result[:max_len] + f"\n... (已截断，还有{len(result) - max_len}个字符)"
            
            return result
            
        except Exception as e:
            return f"执行命令时出错：{str(e)}"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """
        命令安全检查
        
        尽最大努力防止潜在的危险命令执行。
        
        Args:
            command: 要检查的命令
            cwd: 工作目录
        
        Returns:
            如果命令被阻止，返回错误信息；否则返回None
        
        检查项：
            1. 黑名单匹配：检查是否包含危险命令模式
            2. 白名单匹配：如果设置了白名单，检查是否在白名单中
            3. 路径遍历：检查是否尝试访问父目录（..）
            4. 工作目录限制：检查路径是否在工作目录内
        """
        cmd = command.strip()
        lower = cmd.lower()

        # 检查黑名单
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "错误：命令被安全防护阻止（检测到危险模式）"

        # 检查白名单（如果设置）
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "错误：命令被安全防护阻止（不在白名单中）"

        # 工作目录限制
        if self.restrict_to_workspace:
            # 检查路径遍历
            if "..\\" in cmd or "../" in cmd:
                return "错误：命令被安全防护阻止（检测到路径遍历）"

            cwd_path = Path(cwd).resolve()

            # 提取命令中的路径（Windows和POSIX）
            win_paths = re.findall(r"[A-Za-z]:\\[^\\\"']+", cmd)
            posix_paths = re.findall(r"/[^\s\"']+", cmd)

            # 检查每个路径是否在工作目录内
            for raw in win_paths + posix_paths:
                try:
                    p = Path(raw).resolve()
                except Exception:
                    continue
                # 如果路径不在工作目录内，阻止命令
                if cwd_path not in p.parents and p != cwd_path:
                    return "错误：命令被安全防护阻止（路径在工作目录外）"

        return None
