'''大模型交互层：统一管理 AsyncOpenAI 客户端、模型注册表、
token 估算，以及“自动命名 / 上下文压缩”这类轻量调用。'''
import base64
import re
from typing import AsyncIterator

import requests
from openai import AsyncOpenAI

from config import settings

# step01：全局唯一客户端（不要每次请求新建）
client = AsyncOpenAI(base_url=settings.base_url, api_key=settings.api_key)


def available_models() -> list[str]:
    """前端下拉用的模型列表，来自 .env 的 MODELS。"""
    return settings.models or [settings.default_model]


# ---------------- 模型元数据（供前端悬停简介）----------------
# 上下文长度 / 是否多模态 / 特色 / 价格。数据来自 SiliconFlow 官方价格页与
# 首页文案（2026-07），不确定的项用定性表述，避免给出错误数字。
# 键名需与 .env 的 MODELS / 图片模型名一致；未命中的模型回退到通用简介。
MODEL_META: dict[str, dict] = {
    "deepseek-ai/DeepSeek-V4-Pro": {
        "vendor": "DeepSeek", "context": "百万字级（超长上下文）",
        "multimodal": False, "tags": ["旗舰", "超长上下文", "强推理"],
        "price": "¥12 / ¥24 (输入/输出·每百万 token)",
        "desc": "DeepSeek 旗舰对话模型，百万字级超长上下文，综合能力与推理强。文本对话，非多模态。",
    },
    "deepseek-ai/DeepSeek-V4-Flash": {
        "vendor": "DeepSeek", "context": "百万字级（超长上下文）",
        "multimodal": False, "tags": ["轻量", "快速", "低成本"],
        "price": "¥1 / ¥2 (输入/输出·每百万 token)",
        "desc": "DeepSeek-V4 轻量快速版，同样百万字级上下文，成本低、响应快，适合高吞吐。文本对话，非多模态。",
    },
    "moonshotai/Kimi-K2.7-Code": {
        "vendor": "Moonshot", "context": "256K（长上下文）",
        "multimodal": True, "tags": ["代码专精", "多模态", "会看屏幕"],
        "price": "¥6.5 / ¥27 (输入/输出·每百万 token)",
        "desc": "Kimi 代码专精模型，支持视觉（会看屏幕），擅长编程与软件工程。多模态。",
    },
    "Pro/moonshotai/Kimi-K2.6": {
        "vendor": "Moonshot", "context": "256K（长上下文）",
        "multimodal": False, "tags": ["代码", "长文档", "Pro 高并发"],
        "price": "¥6.5 / ¥27 (输入/输出·每百万 token)",
        "desc": "Kimi K2.6 Pro 版，256K 长上下文，擅长代码与长文档处理，Pro 通道更高并发。文本对话，非多模态。",
    },
    "MiniMaxAI/MiniMax-M2.5": {
        "vendor": "MiniMax", "context": "超长上下文（百万级）",
        "multimodal": False, "tags": ["通用对话", "性价比"],
        "price": "¥2.1 / ¥8.4 (输入/输出·每百万 token)",
        "desc": "MiniMax M2.5 通用对话模型，超长上下文，性价比高。文本对话，非多模态。",
    },
    "Qwen/Qwen2.5-7B-Instruct": {
        "vendor": "通义千问", "context": "32K（可扩展至 128K）",
        "multimodal": False, "tags": ["轻量", "便宜", "响应快"],
        "price": "免费 / 极低",
        "desc": "通义千问 7B 轻量模型，32K 上下文，响应快、成本低，适合轻量任务。文本对话，非多模态（视觉版为 Qwen2.5-VL）。",
    },
    # ---- 图片模型 ----
    "Tongyi-MAI/Z-Image-Turbo": {
        "vendor": "通义 Z-Image", "context": "—",
        "multimodal": False, "tags": ["文生图", "高速", "~1s 出图"],
        "price": "¥0.10 / 张",
        "desc": "通义 Z-Image 高速版文生图模型，约 1 秒出图，适合快速生成。专用画图模型，不走文本对话。",
    },
    "Qwen/Qwen-Image-Edit-2509": {
        "vendor": "通义千问", "context": "—",
        "multimodal": False, "tags": ["图片编辑", "图生图", "换背景/改风格"],
        "price": "¥0.30 / 张",
        "desc": "通义千问图片编辑模型（图生图），支持换背景、改风格、加/删元素、调光影、加文字等。专用编辑模型，不走文本对话。",
    },
}


def _generic_meta(model_id: str) -> dict:
    """未登记模型的兜底简介。"""
    vendor = model_id.split("/", 1)[0] if "/" in model_id else ""
    return {
        "vendor": vendor, "context": "—", "multimodal": False, "tags": [],
        "price": "—",
        "desc": f"{model_id}（暂无简介，可在 SiliconFlow 模型广场查看详情）。",
    }


def models_meta(model_ids: list[str]) -> dict[str, dict]:
    """取一批模型的元数据；未登记的回退通用简介。"""
    return {mid: MODEL_META.get(mid) or _generic_meta(mid) for mid in model_ids}


def image_model_names() -> dict:
    """图片任务专用的两个模型名（来自 settings）。前端据此显示正确模型。"""
    return {"gen": settings.image_gen_model, "edit": settings.image_edit_model}


def image_models_meta() -> dict[str, dict]:
    """图片模型的元数据。"""
    return models_meta([settings.image_gen_model, settings.image_edit_model])


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


# ---------------- 图片生成 / 编辑 ----------------
def _image_api_url() -> str:
    """SiliconFlow 图片生成接口（文生图 / 图片编辑共用同一端点）。"""
    return f"{settings.base_url.rstrip('/')}/images/generations"


def _gen_headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }


def _extract_image_bytes(resp_json: dict) -> bytes:
    """从 /images/generations 响应里取出第一张图的二进制。
    优先下载 images[*].url；若直接返回 b64_json 则解码。"""
    images = resp_json.get("images") or []
    if not images:
        raise RuntimeError(f"图片接口未返回图片，原始响应：{resp_json}")
    img = images[0]
    if img.get("b64_json"):
        return base64.b64decode(img["b64_json"])
    url = img.get("url")
    if not url:
        raise RuntimeError(f"图片接口返回项无 url/b64_json：{img}")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content


def generate_image(prompt: str, size: str = None) -> bytes:
    """文生图：调用 image_gen_model，返回生成的图片二进制。"""
    payload = {
        "model": settings.image_gen_model,
        "prompt": prompt,
        "image_size": size or settings.image_size,
        "batch_size": 1,
    }
    resp = requests.post(_image_api_url(), json=payload,
                         headers=_gen_headers(), timeout=120)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"图片生成接口返回非 JSON（HTTP {resp.status_code}）：{resp.text[:200]}")
    if resp.status_code >= 400:
        raise RuntimeError(f"图片生成失败（HTTP {resp.status_code}）：{data}")
    return _extract_image_bytes(data)


def edit_image(prompt: str, image_bytes: bytes, size: str = None) -> bytes:
    """图片编辑：以原图 + 指令调用 image_edit_model，返回编辑后的图片二进制。
    原图以 base64 data URL 放入 image 字段。"""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": settings.image_edit_model,
        "prompt": prompt,
        "image": f"data:image/png;base64,{b64}",
        "image_size": size or settings.image_size,
        "batch_size": 1,
    }
    resp = requests.post(_image_api_url(), json=payload,
                         headers=_gen_headers(), timeout=120)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"图片编辑接口返回非 JSON（HTTP {resp.status_code}）：{resp.text[:200]}")
    if resp.status_code >= 400:
        raise RuntimeError(f"图片编辑失败（HTTP {resp.status_code}）：{data}")
    return _extract_image_bytes(data)
