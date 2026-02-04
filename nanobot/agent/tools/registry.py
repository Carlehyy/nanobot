"""
工具注册表模块：动态管理Agent的工具

这个模块实现了工具的注册、查询和执行机制。
工具是Agent与外部世界交互的接口，通过工具，Agent可以：
- 读写文件
- 执行Shell命令
- 搜索网页
- 发送消息
- 生成子Agent
- 等等...

工具注册表的设计理念：
1. 动态注册：运行时可以注册和注销工具
2. 统一接口：所有工具都实现相同的基类接口
3. 参数验证：执行前自动验证参数
4. 错误处理：捕获并返回友好的错误信息
"""

from typing import Any

from nanobot.agent.tools.base import Tool


class ToolRegistry:
    """
    工具注册表：管理Agent的所有工具
    
    这个类维护一个工具字典，提供工具的注册、查询和执行功能。
    
    核心功能：
    1. 注册工具：将工具实例添加到注册表
    2. 查询工具：根据名称获取工具实例
    3. 获取定义：返回所有工具的OpenAI格式定义（供LLM使用）
    4. 执行工具：根据名称和参数执行工具
    
    属性:
        _tools: 工具字典，键为工具名称，值为工具实例
    
    示例:
        >>> registry = ToolRegistry()
        >>> registry.register(ReadFileTool())
        >>> registry.register(WriteFileTool())
        >>> 
        >>> # 获取所有工具定义
        >>> definitions = registry.get_definitions()
        >>> 
        >>> # 执行工具
        >>> result = await registry.execute("read_file", {"path": "/path/to/file"})
    """
    
    def __init__(self):
        """
        初始化工具注册表
        
        创建一个空的工具字典。
        """
        self._tools: dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """
        注册一个工具
        
        将工具实例添加到注册表中。如果已存在同名工具，会被覆盖。
        
        参数:
            tool: 工具实例（必须继承自Tool基类）
        
        示例:
            >>> registry = ToolRegistry()
            >>> registry.register(ReadFileTool())
            >>> registry.register(WriteFileTool())
        """
        self._tools[tool.name] = tool
    
    def unregister(self, name: str) -> None:
        """
        注销一个工具
        
        从注册表中移除指定名称的工具。如果工具不存在，不会报错。
        
        参数:
            name: 工具名称
        
        示例:
            >>> registry.unregister("read_file")
        """
        self._tools.pop(name, None)
    
    def get(self, name: str) -> Tool | None:
        """
        根据名称获取工具实例
        
        参数:
            name: 工具名称
        
        返回:
            Tool | None: 工具实例，如果不存在则返回None
        
        示例:
            >>> tool = registry.get("read_file")
            >>> if tool:
            ...     result = await tool.execute(path="/path/to/file")
        """
        return self._tools.get(name)
    
    def has(self, name: str) -> bool:
        """
        检查工具是否已注册
        
        参数:
            name: 工具名称
        
        返回:
            bool: 如果工具已注册返回True，否则返回False
        
        示例:
            >>> if registry.has("read_file"):
            ...     print("read_file工具可用")
        """
        return name in self._tools
    
    def get_definitions(self) -> list[dict[str, Any]]:
        """
        获取所有工具的定义（OpenAI格式）
        
        返回所有已注册工具的定义，格式符合OpenAI Function Calling标准。
        这些定义会被发送给LLM，让LLM知道有哪些工具可用以及如何调用。
        
        返回:
            list[dict]: 工具定义列表
        
        定义格式示例:
            [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "读取文件内容",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "文件路径"
                                }
                            },
                            "required": ["path"]
                        }
                    }
                }
            ]
        """
        return [tool.to_schema() for tool in self._tools.values()]
    
    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        执行指定的工具
        
        这是工具执行的统一入口，负责：
        1. 查找工具
        2. 验证参数
        3. 执行工具
        4. 处理异常
        
        参数:
            name: 工具名称
            params: 工具参数字典
        
        返回:
            str: 工具执行结果（总是返回字符串）
        
        异常处理:
            - 工具不存在：返回错误信息
            - 参数无效：返回验证错误信息
            - 执行异常：捕获并返回异常信息
        
        示例:
            >>> result = await registry.execute("read_file", {"path": "/etc/hosts"})
            >>> print(result)
            "127.0.0.1 localhost\n..."
            
            >>> result = await registry.execute("invalid_tool", {})
            >>> print(result)
            "Error: Tool 'invalid_tool' not found"
        """
        # 1. 查找工具
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"

        try:
            # 2. 验证参数
            errors = tool.validate_params(params)
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)
            
            # 3. 执行工具
            return await tool.execute(**params)
        except Exception as e:
            # 4. 处理异常
            return f"Error executing {name}: {str(e)}"
    
    @property
    def tool_names(self) -> list[str]:
        """
        获取所有已注册工具的名称列表
        
        返回:
            list[str]: 工具名称列表
        
        示例:
            >>> print(registry.tool_names)
            ['read_file', 'write_file', 'exec', 'web_search', ...]
        """
        return list(self._tools.keys())
    
    def __len__(self) -> int:
        """
        获取已注册工具的数量
        
        返回:
            int: 工具数量
        
        示例:
            >>> print(len(registry))
            8
        """
        return len(self._tools)
    
    def __contains__(self, name: str) -> bool:
        """
        检查工具是否已注册（支持in操作符）
        
        参数:
            name: 工具名称
        
        返回:
            bool: 如果工具已注册返回True，否则返回False
        
        示例:
            >>> if "read_file" in registry:
            ...     print("read_file工具可用")
        """
        return name in self._tools
