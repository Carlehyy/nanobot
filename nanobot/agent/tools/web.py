"""
Web工具模块

提供Web搜索和网页抓取功能：
- WebSearchTool: 使用Brave Search API搜索网页
- WebFetchTool: 抓取URL并提取可读内容

工具特性：
- 支持HTML到Markdown的转换
- 使用Readability提取主要内容
- 安全的URL验证
- 重定向限制
- 内容长度限制
"""

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from nanobot.agent.tools.base import Tool

# 共享常量
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"
MAX_REDIRECTS = 5  # 限制重定向次数以防止DoS攻击


def _strip_tags(text: str) -> str:
    """
    移除HTML标签并解码实体
    
    Args:
        text: 包含HTML标签的文本
    
    Returns:
        纯文本内容
    
    处理步骤：
        1. 移除<script>标签及其内容
        2. 移除<style>标签及其内容
        3. 移除所有HTML标签
        4. 解码HTML实体（如&nbsp;）
    """
    # 移除script标签
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    # 移除style标签
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    # 移除所有HTML标签
    text = re.sub(r'<[^>]+>', '', text)
    # 解码HTML实体
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """
    规范化空白字符
    
    Args:
        text: 待规范化的文本
    
    Returns:
        规范化后的文本
    
    处理：
        - 将多个空格/制表符合并为单个空格
        - 将3个以上的换行符合并为2个
    """
    # 合并空格和制表符
    text = re.sub(r'[ \t]+', ' ', text)
    # 合并多余的换行符
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """
    验证URL的安全性
    
    Args:
        url: 要验证的URL
    
    Returns:
        (是否有效, 错误信息)
    
    验证规则：
        - 必须是http或https协议
        - 必须包含域名
    """
    try:
        p = urlparse(url)
        # 检查协议
        if p.scheme not in ('http', 'https'):
            return False, f"只允许http/https协议，当前为'{p.scheme or '无'}'"
        # 检查域名
        if not p.netloc:
            return False, "缺少域名"
        return True, ""
    except Exception as e:
        return False, str(e)


class WebSearchTool(Tool):
    """
    Web搜索工具
    
    功能：使用Brave Search API搜索网页
    
    参数：
        query (str): 搜索查询
        count (int): 返回结果数量（1-10），默认5
    
    返回：
        搜索结果列表，包含标题、URL和描述
    
    配置：
        需要设置BRAVE_API_KEY环境变量或在初始化时提供api_key
    
    使用示例：
        tool = WebSearchTool(api_key="your_key")
        result = await tool.execute("Python教程", count=5)
    """
    
    name = "web_search"
    description = "搜索网页。返回标题、URL和摘要。"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询"},
            "count": {"type": "integer", "description": "结果数量（1-10）", "minimum": 1, "maximum": 10}
        },
        "required": ["query"]
    }
    
    def __init__(self, api_key: str | None = None, max_results: int = 5):
        """
        初始化Web搜索工具
        
        Args:
            api_key: Brave Search API密钥（可选，会尝试从环境变量读取）
            max_results: 默认返回的最大结果数
        """
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self.max_results = max_results
    
    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        """
        执行Web搜索
        
        Args:
            query: 搜索查询
            count: 返回结果数量（覆盖默认值）
            **kwargs: 其他参数（忽略）
        
        Returns:
            格式化的搜索结果字符串，或错误信息
        """
        # 检查API密钥
        if not self.api_key:
            return "错误：未配置BRAVE_API_KEY"
        
        try:
            # 确定返回数量（1-10之间）
            n = min(max(count or self.max_results, 1), 10)
            
            # 调用Brave Search API
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()
            
            # 解析结果
            results = r.json().get("web", {}).get("results", [])
            if not results:
                return f"未找到结果：{query}"
            
            # 格式化输出
            lines = [f"搜索结果：{query}\n"]
            for i, item in enumerate(results[:n], 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            
            return "\n".join(lines)
            
        except Exception as e:
            return f"错误：{e}"


class WebFetchTool(Tool):
    """
    网页抓取工具
    
    功能：抓取URL并提取可读内容
    
    参数：
        url (str): 要抓取的URL
        extractMode (str): 提取模式（"markdown"或"text"），默认"markdown"
        maxChars (int): 最大字符数，默认50000
    
    返回：
        JSON格式的结果，包含：
        - url: 原始URL
        - finalUrl: 最终URL（经过重定向后）
        - status: HTTP状态码
        - extractor: 使用的提取器（readability/json/raw）
        - truncated: 是否被截断
        - length: 内容长度
        - text: 提取的文本内容
        - error: 错误信息（如果有）
    
    特性：
        - 使用Readability提取主要内容
        - 支持HTML到Markdown的转换
        - 自动处理JSON响应
        - 限制重定向次数（防止DoS）
        - 内容长度限制
    
    使用示例：
        tool = WebFetchTool(max_chars=10000)
        result = await tool.execute("https://example.com", extractMode="markdown")
    """
    
    name = "web_fetch"
    description = "抓取URL并提取可读内容（HTML → markdown/text）。"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的URL"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }
    
    def __init__(self, max_chars: int = 50000):
        """
        初始化网页抓取工具
        
        Args:
            max_chars: 最大字符数限制
        """
        self.max_chars = max_chars
    
    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        """
        执行网页抓取
        
        Args:
            url: 要抓取的URL
            extractMode: 提取模式（"markdown"或"text"）
            maxChars: 最大字符数（覆盖默认值）
            **kwargs: 其他参数（忽略）
        
        Returns:
            JSON格式的结果字符串
        """
        from readability import Document

        max_chars = maxChars or self.max_chars

        # 验证URL
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL验证失败：{error_msg}", "url": url})

        try:
            # 抓取URL
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
            
            ctype = r.headers.get("content-type", "")
            
            # 根据内容类型处理
            # JSON响应
            if "application/json" in ctype:
                text, extractor = json.dumps(r.json(), indent=2), "json"
            # HTML响应
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                # 使用Readability提取主要内容
                doc = Document(r.text)
                # 根据模式转换为markdown或纯文本
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                # 添加标题
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            # 其他类型（纯文本等）
            else:
                text, extractor = r.text, "raw"
            
            # 检查是否需要截断
            truncated = len(text) > max_chars
            if truncated:
                text = text[:max_chars]
            
            # 返回JSON格式结果
            return json.dumps({
                "url": url,
                "finalUrl": str(r.url),
                "status": r.status_code,
                "extractor": extractor,
                "truncated": truncated,
                "length": len(text),
                "text": text
            })
            
        except Exception as e:
            return json.dumps({"error": str(e), "url": url})
    
    def _to_markdown(self, html: str) -> str:
        """
        将HTML转换为Markdown
        
        Args:
            html: HTML内容
        
        Returns:
            Markdown格式的文本
        
        转换规则：
            - <a>标签 → [文本](URL)
            - <h1>-<h6>标签 → # 标题
            - <li>标签 → - 列表项
            - <p>, <div>等块级元素 → 换行
            - <br>, <hr> → 换行
        """
        # 转换链接
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        # 转换标题
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        # 转换列表项
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        # 转换块级元素为换行
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        # 转换br和hr为换行
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        # 规范化并移除剩余标签
        return _normalize(_strip_tags(text))
