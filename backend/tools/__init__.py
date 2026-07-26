"""工具注册表：统一汇总所有 langchain 工具，供 agent 构建。

工具分组：
- info_tools: 实时信息（天气/汇率/IP/时间/日期），免 key
- github_tool: GitHub 仓库搜索，免 key
- local_tools: 本地计算器 / 二维码生成
- image_tools: 图片生成 / 编辑（复用 llm.py 的画图能力）
- doc_tools: Word / PPT / Excel 生成（PPT 带主题版式系统）

每个工具都自愈（失败返回错误串而非抛异常），避免模型因异常反复重试触发循环。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool

from .info_tools import INFO_TOOLS
from .github_tool import search_github
from .local_tools import LOCAL_TOOLS
from .image_tools import IMAGE_TOOLS
from .doc_tools import DOC_TOOLS

# 全量工具清单（顺序即注册顺序）
ALL_TOOLS: list[BaseTool] = INFO_TOOLS + [search_github] + LOCAL_TOOLS + IMAGE_TOOLS + DOC_TOOLS

# 按名字索引，便于注入上下文参数（如 edit_image 的 conv_id）
_TOOLS_BY_NAME: dict[str, BaseTool] = {t.name: t for t in ALL_TOOLS}


def get_tools() -> list[BaseTool]:
    """返回全量工具列表（agent 默认挂载全部）。"""
    return list(ALL_TOOLS)


def get_tool(name: str) -> BaseTool | None:
    return _TOOLS_BY_NAME.get(name)


# 工具分组描述（供前端“按会话开关工具”面板用）
TOOL_GROUPS: list[dict] = [
    {"key": "info", "name": "实时信息", "icon": "🌐",
     "tools": [t.name for t in INFO_TOOLS]},
    {"key": "github", "name": "GitHub 搜索", "icon": "🐙",
     "tools": [search_github.name]},
    {"key": "local", "name": "本地工具", "icon": "🧮",
     "tools": [t.name for t in LOCAL_TOOLS]},
    {"key": "image", "name": "图片生成/编辑", "icon": "🎨",
     "tools": [t.name for t in IMAGE_TOOLS]},
    {"key": "doc", "name": "文档生成", "icon": "📄",
     "tools": [t.name for t in DOC_TOOLS]},
]


__all__ = ["ALL_TOOLS", "get_tools", "get_tool", "TOOL_GROUPS",
           "INFO_TOOLS", "LOCAL_TOOLS", "IMAGE_TOOLS", "DOC_TOOLS"]
