'''聊天路由：SSE 流式对话 + 自动命名。
SSE 事件类型：token / usage / done / error，前端按行解析 data: ...'''
import json
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import StreamingResponse

import db
from config import settings
from context import build_llm_messages
from llm import generate_title, stream_chat

router = APIRouter()


class ChatRequest(BaseModel):
    conversation_id: str
    query: str = ""
    regenerate: bool = False  # 重新生成：不新增用户消息，复用已有最后一条
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None


@router.post("/chat")
async def chat(req: ChatRequest):
    conv = db.get_conversation(req.conversation_id)
    if not conv:
        return {"code": 404, "message": "会话不存在"}

    prefs = db.get_prefs()
    # 参数：请求体优先，否则用偏好，再否则用 .env
    model = conv.get("model") or prefs.get("default_model") or settings.default_model
    temperature = req.temperature if req.temperature is not None else prefs.get("temperature", 0.5)
    top_p = req.top_p if req.top_p is not None else prefs.get("top_p", 0.5)
    max_tokens = req.max_tokens if req.max_tokens is not None else prefs.get("max_tokens", 1024)
    threshold = prefs.get("compress_threshold") or settings.compress_threshold
    keep_turns = prefs.get("history_keep") or settings.keep_recent_turns

    # step01：用户消息先落库（重新生成时不新增，复用已有最后一条）
    user_mid = ""
    if not req.regenerate:
        user_mid = db.add_message(conv["id"], "user", req.query)

    # step02：组装上下文（可能触发压缩）
    messages = db.list_messages(conv["id"])
    llm_messages, compressed = await build_llm_messages(conv, messages, threshold, keep_turns)

    # step03：流式请求大模型并通过 SSE 推给前端
    async def event_stream():
        full_text = ""
        usage = None
        # 先发 start 事件，回传用户消息 id（供前端回填，支持重生成/编辑）
        yield f"data: {json.dumps({'type': 'start', 'user_message_id': user_mid}, ensure_ascii=False)}\n\n"
        try:
            response = await stream_chat(
                llm_messages, model, temperature, top_p, max_tokens
            )
            async for chunk in response:
                # 带 include_usage 时，最后一个 chunk 的 choices 可能为空
                if getattr(chunk, "usage", None):
                    usage = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)
                if piece:
                    full_text += piece
                    yield f"data: {json.dumps({'type': 'token', 'content': piece}, ensure_ascii=False)}\n\n"
            # step04：把 token 用量随 done 事件回传；助手回复由前端在“完成/停止”时
            # 调用 POST /conversations/{cid}/messages 落库——这样“停止生成”也能保存部分内容。
            usage_dict = {}
            if usage:
                usage_dict = {
                    "prompt_tokens": usage.prompt_tokens,
                    "completion_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                }
            yield f"data: {json.dumps({'type': 'usage', 'compressed': compressed, **usage_dict}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


class TitleRequest(BaseModel):
    user_msg: str
    assistant_msg: str


@router.post("/chat/title")
async def make_title(req: TitleRequest):
    """新对话首轮交换后调用，生成 ≤12 字标题。"""
    try:
        title = await generate_title(req.user_msg, req.assistant_msg)
        return {"code": 200, "title": title}
    except Exception as e:
        return {"code": 500, "message": str(e), "title": "新对话"}
