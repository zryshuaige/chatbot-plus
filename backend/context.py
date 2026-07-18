'''上下文构建与压缩：给大模型组装 messages，并在超阈值时把旧消息压成摘要。
关键原则：DB 始终保留全量历史（前端看全量），只有“发给 LLM 的上下文”被压缩。'''
from typing import Any

import db
from llm import estimate_messages_tokens, summarize_messages
from prompts import get_prompt


def _live_messages(messages: list[dict], summary_until_id: str) -> list[dict]:
    """返回“尚未被摘要覆盖”的活跃消息（位于 summary_until_id 之后）。"""
    if not summary_until_id:
        return list(messages)
    for i, m in enumerate(messages):
        if m["id"] == summary_until_id:
            return messages[i + 1:]
    return list(messages)  # 没找到锚点则视为全部活跃


def _to_llm_role(msg: dict) -> dict:
    return {"role": msg["role"], "content": msg["content"]}


def _assemble(
    system_prompt: str, summary: str, live: list[dict]
) -> list[dict]:
    """按 [系统提示] + [摘要] + [活跃消息] 组装。"""
    parts: list[dict] = [{"role": "system", "content": system_prompt}]
    if summary:
        parts.append(
            {
                "role": "system",
                "content": f"以下是之前对话的摘要，供你参考：\n{summary}",
            }
        )
    parts.extend(_to_llm_role(m) for m in live)
    return parts


async def build_llm_messages(
    conversation: dict,
    messages: list[dict],
    threshold: int,
    keep_turns: int,
) -> tuple[list[dict], bool]:
    """组装发给 LLM 的 messages。

    返回 (messages, compressed)：
    - messages: 最终发给大模型的消息列表
    - compressed: 本次是否触发了压缩
    """
    system_prompt = get_prompt(conversation.get("task"))
    summary = conversation.get("summary") or ""
    summary_until = conversation.get("summary_until_msg_id") or ""

    live = _live_messages(messages, summary_until)
    parts = _assemble(system_prompt, summary, live)

    # 估算是否超阈值；且活跃消息足够多（多于保留窗口+2 条）才压缩
    keep_n = max(keep_turns * 2, 2)  # 保留窗口按“消息条数”计，1 轮=2 条
    est = estimate_messages_tokens(parts)
    if est > threshold and len(live) > keep_n + 2:
        to_summarize = live[:-keep_n]
        new_summary = await summarize_messages(
            [_to_llm_role(m) for m in to_summarize], summary
        )
        until_id = to_summarize[-1]["id"]
        db.set_conversation_summary(conversation["id"], new_summary, until_id)
        # 压缩后重组：系统提示 + 新摘要 + 最近 keep_n 条原文
        parts = _assemble(system_prompt, new_summary, live[-keep_n:])
        return parts, True

    return parts, False
