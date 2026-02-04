"""
文件系统工具模块

提供文件和目录操作的工具集，包括：
- ReadFileTool: 读取文件内容
- WriteFileTool: 写入文件内容
- EditFileTool: 编辑文件（查找替换）
- ListDirTool: 列出目录内容

这些工具使Agent能够与文件系统交互，执行常见的文件操作任务。
"""

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ReadFileTool(Tool):
    """
    读取文件工具
    
    功能：读取指定路径文件的内容
    
    参数：
        path (str): 要读取的文件路径
    
    返回：
        str: 文件内容，或错误信息
    
    错误处理：
        - 文件不存在
        - 不是文件（是目录）
        - 权限不足
        - 其他读取错误
    """
    
    @property
    def name(self) -> str:
        return "read_file"
    
    @property
    def description(self) -> str:
        return "读取指定路径文件的内容。"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要读取的文件路径"
                }
            },
            "required": ["path"]
        }
    
    async def execute(self, path: str, **kwargs: Any) -> str:
        """
        执行文件读取操作
        
        Args:
            path: 文件路径
            **kwargs: 其他参数（忽略）
        
        Returns:
            文件内容字符串，或错误信息
        """
        try:
            # 展开用户目录（~）并转换为Path对象
            file_path = Path(path).expanduser()
            
            # 检查文件是否存在
            if not file_path.exists():
                return f"错误：文件不存在：{path}"
            
            # 检查是否为文件（而非目录）
            if not file_path.is_file():
                return f"错误：不是文件：{path}"
            
            # 读取文件内容（UTF-8编码）
            content = file_path.read_text(encoding="utf-8")
            return content
            
        except PermissionError:
            return f"错误：权限不足：{path}"
        except Exception as e:
            return f"读取文件时出错：{str(e)}"


class WriteFileTool(Tool):
    """
    写入文件工具
    
    功能：将内容写入指定路径的文件
    
    参数：
        path (str): 目标文件路径
        content (str): 要写入的内容
    
    特性：
        - 如果父目录不存在，会自动创建
        - 如果文件已存在，会覆盖原内容
    
    返回：
        str: 成功消息（包含写入字节数），或错误信息
    """
    
    @property
    def name(self) -> str:
        return "write_file"
    
    @property
    def description(self) -> str:
        return "将内容写入指定路径的文件。如果父目录不存在会自动创建。"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要写入的文件路径"
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容"
                }
            },
            "required": ["path", "content"]
        }
    
    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        """
        执行文件写入操作
        
        Args:
            path: 文件路径
            content: 要写入的内容
            **kwargs: 其他参数（忽略）
        
        Returns:
            成功消息或错误信息
        """
        try:
            file_path = Path(path).expanduser()
            
            # 确保父目录存在（递归创建）
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入文件内容（UTF-8编码）
            file_path.write_text(content, encoding="utf-8")
            
            return f"成功写入 {len(content)} 字节到 {path}"
            
        except PermissionError:
            return f"错误：权限不足：{path}"
        except Exception as e:
            return f"写入文件时出错：{str(e)}"


class EditFileTool(Tool):
    """
    编辑文件工具
    
    功能：通过查找替换的方式编辑文件
    
    参数：
        path (str): 要编辑的文件路径
        old_text (str): 要查找的文本（必须精确匹配）
        new_text (str): 替换后的文本
    
    特性：
        - 要求old_text在文件中精确存在
        - 如果old_text出现多次，会提示需要更多上下文
        - 只替换第一次出现的位置
    
    返回：
        str: 成功消息，或错误/警告信息
    """
    
    @property
    def name(self) -> str:
        return "edit_file"
    
    @property
    def description(self) -> str:
        return "通过将old_text替换为new_text来编辑文件。old_text必须在文件中精确存在。"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要编辑的文件路径"
                },
                "old_text": {
                    "type": "string",
                    "description": "要查找并替换的精确文本"
                },
                "new_text": {
                    "type": "string",
                    "description": "替换后的文本"
                }
            },
            "required": ["path", "old_text", "new_text"]
        }
    
    async def execute(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:
        """
        执行文件编辑操作
        
        Args:
            path: 文件路径
            old_text: 要查找的文本
            new_text: 替换后的文本
            **kwargs: 其他参数（忽略）
        
        Returns:
            成功消息、警告或错误信息
        """
        try:
            file_path = Path(path).expanduser()
            
            # 检查文件是否存在
            if not file_path.exists():
                return f"错误：文件不存在：{path}"
            
            # 读取文件内容
            content = file_path.read_text(encoding="utf-8")
            
            # 检查old_text是否存在
            if old_text not in content:
                return f"错误：在文件中未找到old_text。请确保完全匹配。"
            
            # 统计出现次数
            count = content.count(old_text)
            if count > 1:
                return f"警告：old_text在文件中出现了{count}次。请提供更多上下文以使其唯一。"
            
            # 执行替换（只替换第一次出现）
            new_content = content.replace(old_text, new_text, 1)
            file_path.write_text(new_content, encoding="utf-8")
            
            return f"成功编辑 {path}"
            
        except PermissionError:
            return f"错误：权限不足：{path}"
        except Exception as e:
            return f"编辑文件时出错：{str(e)}"


class ListDirTool(Tool):
    """
    列出目录工具
    
    功能：列出指定目录的内容
    
    参数：
        path (str): 要列出的目录路径
    
    特性：
        - 使用emoji区分文件和目录（📁目录 📄文件）
        - 按字母顺序排序
        - 显示空目录提示
    
    返回：
        str: 目录内容列表，或错误信息
    """
    
    @property
    def name(self) -> str:
        return "list_dir"
    
    @property
    def description(self) -> str:
        return "列出指定目录的内容。"
    
    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "要列出的目录路径"
                }
            },
            "required": ["path"]
        }
    
    async def execute(self, path: str, **kwargs: Any) -> str:
        """
        执行目录列出操作
        
        Args:
            path: 目录路径
            **kwargs: 其他参数（忽略）
        
        Returns:
            目录内容列表或错误信息
        """
        try:
            dir_path = Path(path).expanduser()
            
            # 检查目录是否存在
            if not dir_path.exists():
                return f"错误：目录不存在：{path}"
            
            # 检查是否为目录
            if not dir_path.is_dir():
                return f"错误：不是目录：{path}"
            
            # 遍历目录内容
            items = []
            for item in sorted(dir_path.iterdir()):
                # 使用emoji区分文件和目录
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")
            
            # 处理空目录
            if not items:
                return f"目录 {path} 是空的"
            
            return "\n".join(items)
            
        except PermissionError:
            return f"错误：权限不足：{path}"
        except Exception as e:
            return f"列出目录时出错：{str(e)}"
