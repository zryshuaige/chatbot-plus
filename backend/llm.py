'''大模型交互层：统一管理 AsyncOpenAI 客户端、模型注册表、
token 估算，以及“自动命名 / 上下文压缩”这类轻量调用。'''
import re
from typing import AsyncIterator

from openai import AsyncOpenAI

from config import settings

# step01：全局唯一客户端（不要每次请求新建）
client = AsyncOpenAI(base_url=settings.base_url, api_key=settings.api_key)


def available_models() -> list[str]:
    """前端下拉用的模型列表，来自 .env 的 MODELS。"""
    return settings.models or [settings.default_model]


# ---------------- token 估算 ----------------
_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")


def estimate_tokens(text: str) -> int:
    """不依赖 tiktoken 的粗略估算：中文按 1 字≈1.5 token，其余按 4 字符≈1 token。
    只用于触发压缩阈值的判断，不需要精确。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return int(cjk * 1.5 + other / 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算一组 messages 的总 token（含每条 role 的固定开销）。"""
    total = 0
    for m in messages:
        total += 4  # role/separators 固定开销
        total += estimate_tokens(m.get("content", ""))
    return total


# ---------------- 流式对话 ----------------
async def stream_chat(
    messages: list[dict],
    model: str,
    temperature: float = 0.5,
    top_p: float = 0.5,
    max_tokens: int = 1024,
) -> AsyncIterator:
    """流式发起对话。开启 include_usage 以便末尾拿到 token 用量。"""
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    return response


# ---------------- 轻量调用：自动命名 ----------------
async def generate_title(user_msg: str, assistant_msg: str) -> str:
    """根据首轮问答生成 ≤12 字的会话标题。"""
    prompt = (
        "请用不超过 12 个汉字为下面这段对话起一个简洁标题，"
        "只输出标题本身，不要引号、不要标点、不要解释。\n\n"
        f"用户：{user_msg[:300]}\n助手：{assistant_msg[:300]}"
    )
    resp = await client.chat.completions.create(
        model=settings.utility_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=30,
        temperature=0.3,
    )
    title = (resp.choices[0].message.content or "").strip().strip("\"'""''「」")
    # 防御：只取第一行，截断过长标题
    title = title.splitlines()[0][:20] if title else "新对话"
    return title or "新对话"


# ---------------- 轻量调用：上下文压缩 ----------------
async def summarize_messages(
    to_summarize: list[dict], existing_summary: str
) -> str:
    """把一组旧消息压缩成摘要；若已有摘要则在其基础上增量更新。"""
    transcript = "\n".join(
        f"{'用户' if m['role'] == 'user' else '助手'}：{m['content']}"
        for m in to_summarize
    )
    base = (
        f"已有摘要：\n{existing_summary}\n\n" if existing_summary else ""
    )
    prompt = (
        f"{base}请把以下对话整理成一份简洁的结构化摘要，"
        "保留关键事实、用户意图、已达成结论与待办，删除寒暄与冗余。"
        "用要点形式，控制在 300 字以内。\n\n"
        f"{transcript}"
    )
    resp = await client.chat.completions.create(
        model=settings.utility_model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()
