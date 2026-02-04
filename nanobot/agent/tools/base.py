"""
工具基类模块：定义Agent工具的抽象接口

这个模块定义了所有工具必须实现的基类接口。
工具是Agent与外部世界交互的能力，通过工具，Agent可以：
- 读写文件
- 执行命令
- 搜索网页
- 发送消息
- 等等...

工具的设计遵循OpenAI Function Calling标准，包括：
1. 名称：工具的唯一标识符
2. 描述：工具的功能说明（供LLM理解）
3. 参数：JSON Schema格式的参数定义
4. 执行：实际的工具逻辑
"""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """
    工具抽象基类
    
    所有工具都必须继承这个类并实现抽象方法。
    
    工具的生命周期：
    1. 定义：实现name、description、parameters属性
    2. 注册：添加到ToolRegistry
    3. 发现：LLM通过get_definitions()获取工具列表
    4. 调用：LLM决定调用某个工具
    5. 验证：validate_params()验证参数
    6. 执行：execute()执行工具逻辑
    7. 返回：返回字符串结果给LLM
    
    类属性:
        _TYPE_MAP: JSON Schema类型到Python类型的映射
    
    抽象属性:
        name: 工具名称
        description: 工具描述
        parameters: 参数定义（JSON Schema）
    
    抽象方法:
        execute: 执行工具逻辑
    
    示例:
        >>> class MyTool(Tool):
        ...     @property
        ...     def name(self) -> str:
        ...         return "my_tool"
        ...     
        ...     @property
        ...     def description(self) -> str:
        ...         return "这是我的工具"
        ...     
        ...     @property
        ...     def parameters(self) -> dict:
        ...         return {
        ...             "type": "object",
        ...             "properties": {
        ...                 "arg1": {"type": "string", "description": "参数1"}
        ...             },
        ...             "required": ["arg1"]
        ...         }
        ...     
        ...     async def execute(self, **kwargs) -> str:
        ...         return f"执行结果: {kwargs['arg1']}"
    """
    
    # JSON Schema类型到Python类型的映射
    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),  # number可以是int或float
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    
    @property
    @abstractmethod
    def name(self) -> str:
        """
        工具名称（必须实现）
        
        返回工具的唯一标识符，用于LLM调用工具时指定。
        
        命名规范：
        - 使用小写字母和下划线
        - 简短且具有描述性
        - 例如：read_file、web_search、exec
        
        返回:
            str: 工具名称
        """
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """
        工具描述（必须实现）
        
        返回工具功能的详细说明，供LLM理解工具的用途。
        
        描述规范：
        - 清晰说明工具的功能
        - 说明何时应该使用这个工具
        - 可以包含使用示例
        
        返回:
            str: 工具描述
        """
        pass
    
    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """
        参数定义（必须实现）
        
        返回工具参数的JSON Schema定义。
        
        JSON Schema格式：
        {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "参数1的说明"
                },
                "param2": {
                    "type": "integer",
                    "description": "参数2的说明",
                    "minimum": 0
                }
            },
            "required": ["param1"]
        }
        
        支持的类型：
        - string: 字符串
        - integer: 整数
        - number: 数字（整数或浮点数）
        - boolean: 布尔值
        - array: 数组
        - object: 对象
        
        返回:
            dict: JSON Schema格式的参数定义
        """
        pass
    
    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        执行工具（必须实现）
        
        这是工具的核心逻辑，执行实际的操作并返回结果。
        
        参数:
            **kwargs: 工具的参数（由LLM提供）
        
        返回:
            str: 工具执行结果（总是返回字符串）
        
        异常:
            可以抛出异常，会被ToolRegistry捕获并转换为错误消息
        
        注意:
            - 必须是异步方法（async def）
            - 返回值必须是字符串
            - 如果操作失败，可以返回错误描述或抛出异常
        """
        pass

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """
        验证工具参数
        
        根据JSON Schema定义验证参数是否合法。
        
        验证内容：
        1. 类型检查：参数类型是否匹配
        2. 必需参数：是否缺少必需参数
        3. 枚举值：是否在允许的枚举值中
        4. 数值范围：是否在最小值和最大值之间
        5. 字符串长度：是否在最小长度和最大长度之间
        6. 嵌套验证：递归验证对象和数组
        
        参数:
            params: 要验证的参数字典
        
        返回:
            list[str]: 错误列表（如果为空则表示验证通过）
        
        示例:
            >>> tool = MyTool()
            >>> errors = tool.validate_params({"arg1": "value"})
            >>> if errors:
            ...     print("参数错误:", errors)
            ... else:
            ...     print("参数验证通过")
        """
        schema = self.parameters or {}
        
        # 确保schema是object类型
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        
        # 递归验证
        return self._validate(params, {**schema, "type": "object"}, "")

    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        """
        递归验证参数（内部方法）
        
        这是一个递归方法，用于验证嵌套的参数结构。
        
        参数:
            val: 要验证的值
            schema: JSON Schema定义
            path: 当前路径（用于错误消息）
        
        返回:
            list[str]: 错误列表
        
        验证逻辑：
        1. 类型检查
        2. 枚举值检查
        3. 数值范围检查
        4. 字符串长度检查
        5. 对象属性检查（递归）
        6. 数组元素检查（递归）
        """
        t = schema.get("type")
        label = path or "parameter"
        
        # 1. 类型检查
        if t in self._TYPE_MAP and not isinstance(val, self._TYPE_MAP[t]):
            return [f"{label} should be {t}"]
        
        errors = []
        
        # 2. 枚举值检查
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        
        # 3. 数值范围检查
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        
        # 4. 字符串长度检查
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")
        
        # 5. 对象属性检查（递归）
        if t == "object":
            props = schema.get("properties", {})
            
            # 检查必需属性
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            
            # 递归验证每个属性
            for k, v in val.items():
                if k in props:
                    errors.extend(self._validate(v, props[k], path + '.' + k if path else k))
        
        # 6. 数组元素检查（递归）
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                errors.extend(self._validate(item, schema["items"], f"{path}[{i}]" if path else f"[{i}]"))
        
        return errors
    
    def to_schema(self) -> dict[str, Any]:
        """
        转换为OpenAI Function Calling格式
        
        将工具定义转换为OpenAI Function Calling标准格式，
        供LLM使用。
        
        返回:
            dict: OpenAI格式的工具定义
        
        格式示例:
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
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }
