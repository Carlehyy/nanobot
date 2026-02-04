"""
技能加载器模块

为Agent提供技能加载和管理功能。技能是教会Agent如何使用特定工具或执行特定任务的Markdown文件。
"""

import json
import os
import re
import shutil
from pathlib import Path

# 默认的内置技能目录（相对于此文件）
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillsLoader:
    """
    Agent技能加载器
    
    功能：
        - 加载和管理Agent技能
        - 支持工作空间技能和内置技能
        - 检查技能依赖和可用性
        - 渐进式加载（先加载摘要，需要时再加载完整内容）
    
    技能结构：
        skills/
        └── skill_name/
            └── SKILL.md  # 技能文档（Markdown格式）
    
    技能文件格式：
        ---
        description: 技能描述
        metadata: {"nanobot": {"requires": {"bins": ["git"], "env": ["API_KEY"]}, "always": false}}
        ---
        
        # 技能内容
        ...
    
    优先级：
        工作空间技能 > 内置技能
    
    使用示例：
        loader = SkillsLoader(workspace=Path("~/.nanobot"))
        skills = loader.list_skills()
        content = loader.load_skill("git-helper")
    """
    
    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        """
        初始化技能加载器
        
        Args:
            workspace: 工作空间目录
            builtin_skills_dir: 内置技能目录（可选，默认使用BUILTIN_SKILLS_DIR）
        """
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
    
    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        列出所有可用的技能
        
        Args:
            filter_unavailable: 是否过滤掉依赖未满足的技能
        
        Returns:
            技能信息字典列表，包含'name'、'path'、'source'字段
        
        说明：
            - 工作空间技能优先级高于内置技能
            - 如果工作空间和内置都有同名技能，只返回工作空间的
        """
        skills = []
        
        # 工作空间技能（最高优先级）
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})
        
        # 内置技能
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    # 如果工作空间没有同名技能，才添加内置技能
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})
        
        # 根据依赖过滤
        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills
    
    def load_skill(self, name: str) -> str | None:
        """
        根据名称加载技能
        
        Args:
            name: 技能名称（目录名）
        
        Returns:
            技能内容，如果未找到返回None
        
        查找顺序：
            1. 工作空间技能
            2. 内置技能
        """
        # 先检查工作空间
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")
        
        # 再检查内置技能
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")
        
        return None
    
    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        加载指定的技能以包含在Agent上下文中
        
        Args:
            skill_names: 要加载的技能名称列表
        
        Returns:
            格式化的技能内容
        
        格式：
            ### Skill: skill_name
            
            <技能内容>
            
            ---
            
            ### Skill: another_skill
            ...
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                # 移除frontmatter（YAML元数据）
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
        
        return "\n\n---\n\n".join(parts) if parts else ""
    
    def build_skills_summary(self) -> str:
        """
        构建所有技能的摘要（名称、描述、路径、可用性）
        
        用于渐进式加载：Agent可以先看到技能列表，需要时再使用read_file读取完整内容
        
        Returns:
            XML格式的技能摘要
        
        格式：
            <skills>
              <skill available="true">
                <name>git-helper</name>
                <description>Git操作助手</description>
                <location>/path/to/SKILL.md</location>
              </skill>
              <skill available="false">
                <name>docker-helper</name>
                <description>Docker操作助手</description>
                <location>/path/to/SKILL.md</location>
                <requires>CLI: docker</requires>
              </skill>
            </skills>
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""
        
        def escape_xml(s: str) -> str:
            """转义XML特殊字符"""
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)
            
            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")
            
            # 对于不可用的技能，显示缺失的依赖
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")
            
            lines.append(f"  </skill>")
        lines.append("</skills>")
        
        return "\n".join(lines)
    
    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """
        获取缺失的依赖描述
        
        Args:
            skill_meta: 技能元数据
        
        Returns:
            缺失依赖的描述字符串，如"CLI: docker, ENV: API_KEY"
        """
        missing = []
        requires = skill_meta.get("requires", {})
        
        # 检查命令行工具
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        
        # 检查环境变量
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        
        return ", ".join(missing)
    
    def _get_skill_description(self, name: str) -> str:
        """
        从技能的frontmatter中获取描述
        
        Args:
            name: 技能名称
        
        Returns:
            技能描述，如果没有则返回技能名称
        """
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # 回退到技能名称
    
    def _strip_frontmatter(self, content: str) -> str:
        """
        从Markdown内容中移除YAML frontmatter
        
        Args:
            content: Markdown内容
        
        Returns:
            移除frontmatter后的内容
        
        Frontmatter格式：
            ---
            key: value
            ---
            
            内容...
        """
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content
    
    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """
        从frontmatter中解析nanobot元数据JSON
        
        Args:
            raw: 原始元数据字符串
        
        Returns:
            nanobot元数据字典
        
        格式：
            metadata: {"nanobot": {"requires": {...}, "always": true}}
        """
        try:
            data = json.loads(raw)
            return data.get("nanobot", {}) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def _check_requirements(self, skill_meta: dict) -> bool:
        """
        检查技能依赖是否满足
        
        Args:
            skill_meta: 技能元数据
        
        Returns:
            依赖是否全部满足
        
        检查项：
            - bins: 命令行工具是否存在
            - env: 环境变量是否设置
        """
        requires = skill_meta.get("requires", {})
        
        # 检查命令行工具
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        
        # 检查环境变量
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        
        return True
    
    def _get_skill_meta(self, name: str) -> dict:
        """
        获取技能的nanobot元数据
        
        Args:
            name: 技能名称
        
        Returns:
            nanobot元数据字典
        """
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))
    
    def get_always_skills(self) -> list[str]:
        """
        获取标记为always=true且依赖满足的技能
        
        Returns:
            技能名称列表
        
        说明：
            always=true的技能会自动加载到Agent上下文中
        """
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result
    
    def get_skill_metadata(self, name: str) -> dict | None:
        """
        从技能的frontmatter中获取元数据
        
        Args:
            name: 技能名称
        
        Returns:
            元数据字典，如果未找到返回None
        
        解析规则：
            简单的YAML解析，支持key: value格式
        """
        content = self.load_skill(name)
        if not content:
            return None
        
        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                # 简单的YAML解析
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"\'')
                return metadata
        
        return None
