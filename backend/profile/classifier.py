"""隐式用户画像分类器。

设计目标（用户硬性约束）：
1. **用户不感知**——不弹窗、不让用户选、没有显式开关，只在 sidebar 给一行小 caption。
2. **提示词要轻**——只追加几行后缀，不替换任务系统提示；保证体感差异不显著。
3. **自动判断**——根据用户近 N 轮消息的关键词 + 长度 + 追问密度等信号聚合判定。
4. **本地完成**——LLM 调用走本项目的 utility_model，不上传任何外部。

信号维度：
- **user_intent**: research（研究型）/ learn（学习型）/ creative（创意型）/ general（通用）
- **detail_level**: brief（简洁）/ normal（适中）/ deep（详细）

工作流程：
1. 每条用户消息落入 messages 表后，调用 `accumulate_signals(msg)` 累计信号
2. 信号累计满 `WINDOW_SIZE` 轮（或单次"高强度信号"如"详细解释"）
3. 调用 `classify_profile()` 让 LLM 把信号 JSON 解析成 {intent, detail_level}
4. 写入 prefs，下次对话生效；切换平滑（不改当前正在生成的回复）
5. 用户点「🧹 重置模式」时清回默认
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from typing import Optional

from config import settings
from llm import client as _openai_client
import db


# 默认参数
DEFAULT_INTENT = "general"
DEFAULT_DETAIL = "normal"
WINDOW_SIZE = 5            # 累计多少轮用户消息再触发一次 LLM 分类
HIGH_STRENGTH_KEYWORDS = { # 单次出现就足以触发即时分类
    "详细解释", "详细说明", "深入分析", "深入浅出", "完整推导", "穷举", "完整列出",
    "简短回答", "简洁点", "一句话", "简短点", "别展开",
}
RESEARCH_HINTS = {
    "为什么", "原理", "论文", "对比", "文献", "证明", "深入", "详细解释", "为什么不是",
    "机制", "本质", "区别", "权衡", "局限", "why", "how does", "prove", "reference",
    "differences", "tradeoff", "literature",
}
LEARN_HINTS = {
    "教我", "怎么用", "教程", "入门", "步骤", "例子", "演示", "如何", "怎么做",
    "教一下", "步骤", "快速入门", "teach me", "tutorial", "example", "step by step",
    "how to", "show me",
}
CREATIVE_HINTS = {
    "写一首", "故事", "创意", "文案", "比喻", "想象", "起名", "名字", "诗", "广告语",
    "宣传", "梗", "点子", "灵感", "write a poem", "story", "imagine", "brainstorm",
    "tagline", "slogan",
}
DEEP_HINTS = {
    "详细", "完整", "穷举", "全部", "详细解释", "展开", "完整推导", "深入",
    "完整列出", "comprehensive", "exhaustive", "deep", "detailed", "in detail",
}
BRIEF_HINTS = {
    "简洁", "简短", "一句话", "简短点", "别展开", "TL;DR", "brief", "short",
    "in one sentence", "concise",
}

# 最近 N 条用户消息的累计信号缓存（in-memory；写库由写入 prefs 完成）
_signal_window: deque[dict] = deque(maxlen=WINDOW_SIZE * 2)
_last_classified_at: float = 0.0
_CLASSIFY_DEBOUNCE_S = 30   # 两次 LLM 分类至少间隔 30s


# ---------------- 信号累计 ----------------
def accumulate_signals(user_msg: str) -> dict:
    """从一条用户消息提取特征信号，返回可序列化的 dict。

    特征包括：消息长度、关键词命中、是否含代码块、是否问号结尾、是否追问等。
    """
    text = (user_msg or "").strip()
    signals: dict = {
        "len_chars": len(text),
        "has_question": text.endswith("?") or text.endswith("？"),
        "has_code_block": "```" in text or "    " in text,  # 缩进代码
        "hits_research": _count_hits(text, RESEARCH_HINTS),
        "hits_learn":    _count_hits(text, LEARN_HINTS),
        "hits_creative": _count_hits(text, CREATIVE_HINTS),
        "hits_deep":     _count_hits(text, DEEP_HINTS),
        "hits_brief":    _count_hits(text, BRIEF_HINTS),
        "is_short":      len(text) < 30,
        "is_long":       len(text) > 200,
        "preview": text[:80],
    }
    _signal_window.append(signals)
    return signals


def _count_hits(text: str, keywords: set[str]) -> int:
    n = 0
    for k in keywords:
        if k in text:
            n += 1
    return n


def should_classify_now() -> bool:
    """判定是否到触发 LLM 分类的时机：
    1. 信号窗口累计满 WINDOW_SIZE 条
    2. 任一信号是高强度（深度/极简意图）—— 立即触发
    3. 距上次分类超过 30s（debounce）
    """
    global _last_classified_at
    now = time.monotonic()
    if now - _last_classified_at < _CLASSIFY_DEBOUNCE_S:
        return False
    if not _signal_window:
        return False
    if len(_signal_window) < WINDOW_SIZE:
        # 检查高强度
        latest = _signal_window[-1]
        if (latest["hits_deep"] >= 1 or latest["hits_brief"] >= 1
                or latest["hits_research"] >= 2 or latest["hits_creative"] >= 2):
            return True
        return False
    return True


def mark_classified() -> None:
    global _last_classified_at
    _last_classified_at = time.monotonic()


def reset_window() -> None:
    _signal_window.clear()


# ---------------- LLM 分类 ----------------
async def classify_profile(prefs: dict) -> tuple[str, str]:
    """调用 utility_model 把最近窗口的信号判成 (intent, detail_level)。
    失败时返回原值不变（profile 信号是软提示，不阻塞对话）。"""
    if not _signal_window:
        return prefs.get("user_intent") or DEFAULT_INTENT, prefs.get("detail_level") or DEFAULT_DETAIL

    # 把窗口信号压缩成一段 prompt 让 LLM 决策
    summary = json.dumps(list(_signal_window), ensure_ascii=False, indent=None)
    sys_prompt = (
        "你是「用户提问风格分类器」。根据下面 JSON 信号，判断用户当前的提问倾向，"
        "输出严格 JSON：{\"intent\": \"research|learn|creative|general\", \"detail_level\": \"brief|normal|deep\"}\n\n"
        "判定规则：\n"
        "- research：用户偏好深挖原因、对比、原理、引用文献的回答\n"
        "- learn：用户偏好教程式、步骤化、配例子的入门级解释\n"
        "- creative：用户在做创意/写作/文案/命名\n"
        "- general：都不明显\n"
        "- brief：用户反复要简短 / 单句\n"
        "- deep：用户反复要详细 / 完整 / 展开\n"
        "- normal：两者都不明显\n\n"
        "只输出 JSON，不要任何解释。"
    )
    try:
        resp = await _openai_client.chat.completions.create(
            model=settings.utility_model,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"近 {len(_signal_window)} 条用户消息的信号：\n{summary[:2000]}"},
            ],
            max_tokens=60,
            temperature=0.1,
            timeout=8,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # 提取 JSON（容错：可能被 markdown 包住）
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return DEFAULT_INTENT, DEFAULT_DETAIL
        data = json.loads(m.group(0))
        intent = data.get("intent") or DEFAULT_INTENT
        detail = data.get("detail_level") or DEFAULT_DETAIL
        if intent not in ("research", "learn", "creative", "general"):
            intent = DEFAULT_INTENT
        if detail not in ("brief", "normal", "deep"):
            detail = DEFAULT_DETAIL
        return intent, detail
    except Exception:
        # 分类失败不阻塞对话：保持现状
        return prefs.get("user_intent") or DEFAULT_INTENT, prefs.get("detail_level") or DEFAULT_DETAIL


# ---------------- 写库 ----------------
def persist_profile(intent: str, detail_level: str) -> None:
    """把最新画像写到 prefs；同时清空 in-memory 信号窗口。"""
    db.update_prefs(
        user_intent=intent,
        detail_level=detail_level,
        profile_updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        profile_version=(db.get_prefs().get("profile_version", 0) or 0) + 1,
    )
    reset_window()
    mark_classified()


def reset_profile() -> None:
    """用户主动重置：画像回默认，信号窗口清空。"""
    db.update_prefs(
        user_intent=DEFAULT_INTENT,
        detail_level=DEFAULT_DETAIL,
        profile_signals="{}",
        profile_updated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    reset_window()
    mark_classified()