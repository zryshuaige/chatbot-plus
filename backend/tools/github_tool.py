"""GitHub 仓库搜索工具：调用 GitHub 公共 API（免 token，匿名 60 次/小时）。
特别契合“代码编程”任务：能推荐真实可用、有 star 的库。"""
from __future__ import annotations

import requests
from langchain.tools import tool

from .info_tools import cached  # 复用 TTL 缓存装饰器

_GH_API = "https://api.github.com"


@cached(600)
def _search_repos(query: str, limit: int) -> list[dict]:
    r = requests.get(
        f"{_GH_API}/search/repositories",
        params={"q": query, "sort": "stars", "order": "desc", "per_page": limit},
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    return [{
        "name": it["full_name"],
        "stars": it["stargazers_count"],
        "lang": it.get("language") or "-",
        "url": it["html_url"],
        "desc": (it.get("description") or "")[:200],
        "updated": (it.get("updated_at") or "")[:10],
    } for it in items]


@tool
def search_github(query: str, limit: int = 5) -> str:
    """在 GitHub 上按关键词搜索热门开源仓库（按 star 降序），返回名称、star 数、语言、简介与链接。
    适合用户问“有没有做 XX 的开源库 / 推荐几个 Python 的 XX 库 / 这个需求有什么现成方案”。

    Args:
        query: 搜索关键词，如 "python web crawler" "react state management" "图像分割"。
        limit: 返回条数，1-10，默认 5。
    """
    limit = max(1, min(10, int(limit or 5)))
    try:
        repos = _search_repos(query, limit)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            return "查询失败：GitHub 匿名接口额度用尽（60次/小时），请稍后再试。"
        return f"查询失败：GitHub 搜索出错（{e}）。"
    except Exception as e:
        return f"查询失败：GitHub 搜索出错（{e}）。"
    if not repos:
        return f"未找到与「{query}」相关的仓库，建议换个关键词。"
    lines = [f"GitHub 上「{query}」的热门仓库（共 {len(repos)} 个）："]
    for i, it in enumerate(repos, 1):
        lines.append(
            f"{i}. {it['name']}  ⭐{it['stars']}  [{it['lang']}]  更新 {it['updated']}\n"
            f"   {it['desc']}\n   {it['url']}"
        )
    return "\n".join(lines)
