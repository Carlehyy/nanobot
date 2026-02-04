"""
记忆系统模块

为Agent提供持久化记忆功能，支持：
- 每日笔记（memory/YYYY-MM-DD.md）
- 长期记忆（MEMORY.md）
- 最近N天的记忆检索
"""

from pathlib import Path
from datetime import datetime

from nanobot.utils.helpers import ensure_dir, today_date


class MemoryStore:
    """
    Agent记忆存储系统
    
    功能：
        - 每日笔记：自动按日期创建和管理笔记文件
        - 长期记忆：存储重要的持久化信息
        - 记忆检索：获取最近N天的记忆
        - 上下文构建：为Agent提供记忆上下文
    
    文件结构：
        workspace/
        └── memory/
            ├── MEMORY.md          # 长期记忆
            ├── 2024-01-01.md      # 每日笔记
            ├── 2024-01-02.md
            └── ...
    
    使用示例：
        store = MemoryStore(Path("~/.nanobot"))
        store.append_today("用户喜欢Python")
        context = store.get_memory_context()
    """
    
    def __init__(self, workspace: Path):
        """
        初始化记忆存储
        
        Args:
            workspace: 工作空间目录路径
        """
        self.workspace = workspace
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
    
    def get_today_file(self) -> Path:
        """
        获取今天的记忆文件路径
        
        Returns:
            今天的记忆文件路径（memory/YYYY-MM-DD.md）
        """
        return self.memory_dir / f"{today_date()}.md"
    
    def read_today(self) -> str:
        """
        读取今天的记忆笔记
        
        Returns:
            今天的记忆内容，如果文件不存在返回空字符串
        """
        today_file = self.get_today_file()
        if today_file.exists():
            return today_file.read_text(encoding="utf-8")
        return ""
    
    def append_today(self, content: str) -> None:
        """
        追加内容到今天的记忆笔记
        
        Args:
            content: 要追加的内容
        
        行为：
            - 如果今天的文件已存在，追加到末尾
            - 如果今天的文件不存在，创建新文件并添加日期标题
        """
        today_file = self.get_today_file()
        
        if today_file.exists():
            # 文件已存在，追加内容
            existing = today_file.read_text(encoding="utf-8")
            content = existing + "\n" + content
        else:
            # 新文件，添加日期标题
            header = f"# {today_date()}\n\n"
            content = header + content
        
        today_file.write_text(content, encoding="utf-8")
    
    def read_long_term(self) -> str:
        """
        读取长期记忆
        
        Returns:
            长期记忆内容（MEMORY.md），如果文件不存在返回空字符串
        """
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""
    
    def write_long_term(self, content: str) -> None:
        """
        写入长期记忆
        
        Args:
            content: 要写入的内容
        
        说明：
            会覆盖MEMORY.md的现有内容
        """
        self.memory_file.write_text(content, encoding="utf-8")
    
    def get_recent_memories(self, days: int = 7) -> str:
        """
        获取最近N天的记忆
        
        Args:
            days: 要回溯的天数，默认7天
        
        Returns:
            合并的记忆内容，各天之间用分隔线分隔
        
        说明：
            - 从今天开始往前数N天
            - 只返回存在的记忆文件
            - 按时间倒序排列（最新的在前）
        """
        from datetime import timedelta
        
        memories = []
        today = datetime.now().date()
        
        # 遍历最近N天
        for i in range(days):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            file_path = self.memory_dir / f"{date_str}.md"
            
            # 如果文件存在，添加到列表
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                memories.append(content)
        
        # 用分隔线连接各天的记忆
        return "\n\n---\n\n".join(memories)
    
    def list_memory_files(self) -> list[Path]:
        """
        列出所有记忆文件
        
        Returns:
            记忆文件路径列表，按日期倒序排列（最新的在前）
        """
        if not self.memory_dir.exists():
            return []
        
        # 查找所有日期格式的记忆文件
        files = list(self.memory_dir.glob("????-??-??.md"))
        # 按日期倒序排序
        return sorted(files, reverse=True)
    
    def get_memory_context(self) -> str:
        """
        获取Agent的记忆上下文
        
        Returns:
            格式化的记忆上下文，包含长期记忆和今天的笔记
        
        格式：
            ## Long-term Memory
            <长期记忆内容>
            
            ## Today's Notes
            <今天的笔记内容>
        
        说明：
            这个方法用于构建Agent的上下文，让Agent能够"记住"重要信息
        """
        parts = []
        
        # 添加长期记忆
        long_term = self.read_long_term()
        if long_term:
            parts.append("## Long-term Memory\n" + long_term)
        
        # 添加今天的笔记
        today = self.read_today()
        if today:
            parts.append("## Today's Notes\n" + today)
        
        return "\n\n".join(parts) if parts else ""
