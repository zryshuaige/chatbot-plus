'''聊天路由：SSE 流式对话 + 自动命名。
SSE 事件类型：token / usage / done / error，前端按行解析 data: ...'''
import asyncio
import base64
import json
import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import StreamingResponse

import db
from config import settings
from context import build_llm_messages
from documents import TOOL_GUIDE, dispatch_tool, tools_for_api
from llm import edit_image, generate_image, generate_title, stream_chat

router = APIRouter()

# 图片任务代号 -> 处理方式。这些任务不走文本对话流，直接调专用画图/编辑模型。
IMAGE_TASKS = {"image_gen", "image_edit"}

# 图片扩展名 -> MIME（构造 data URL 用）
_IMG_MIME = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
}
# 大图缩放上限：超过该边长的图片按比例缩小，避免 base64 撑爆请求体 /
# 触发服务商尺寸上限（OpenAI 推荐 1568）。PIL 不可用或失败则回退原图。
_IMG_MAX_SIDE = 1568


def _maybe_downscale(raw: bytes, mime: str, filename: str) -> tuple[bytes, str]:
    """超大图片按 _IMG_MAX_SIDE 等比缩放；失败回退原图。"""
    try:
        from PIL import Image  # 延迟导入：仅处理图片时才需要
        img = Image.open(BytesIO(raw))
        if max(img.size) <= _IMG_MAX_SIDE:
            return raw, mime
        img.thumbnail((_IMG_MAX_SIDE, _IMG_MAX_SIDE))
        ext = (filename or "").rsplit(".", 1)[-1].lower()
        fmt, out_mime = ("PNG", "image/png") if ext == "png" else ("JPEG", "image/jpeg")
        if fmt == "JPEG" and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format=fmt)
        return buf.getvalue(), out_mime
    except Exception:
        return raw, mime


def _image_url_parts(file_ids: list[str]) -> list[dict]:
    """把图片文件读成 base64 data URL，组装成 OpenAI 多模态 image_url 片段。
    文本类/读取出错/非图片一律跳过。"""
    parts: list[dict] = []
    for fr in db.get_files(file_ids):
        if fr.get("kind") != "image":
            continue
        try:
            raw = Path(fr["path"]).read_bytes()
        except Exception:
            continue
        ext = (fr.get("filename") or "").rsplit(".", 1)[-1].lower()
        mime = _IMG_MIME.get(ext, "image/png")
        raw, mime = _maybe_downscale(raw, mime, fr.get("filename") or "")
        b64 = base64.b64encode(raw).decode("ascii")
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })
    return parts


def _save_image_bytes(raw: bytes, prefix: str = "gen") -> dict:
    """把生成/编辑得到的图片字节落盘并入库，返回附件元数据。
    用 PIL 探测真实扩展名，无法识别时按 png 存储。"""
    ext = "png"
    try:
        from PIL import Image
        fmt = Image.open(BytesIO(raw)).format or ""
        ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif",
               "BMP": "bmp"}.get(fmt.upper(), "png")
    except Exception:
        ext = "png"
    save_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
    save_path = settings.files_dir / save_name
    save_path.write_bytes(raw)
    fid = db.add_file(
        filename=save_name, kind="image", size=len(raw),
        chars=0, text="", path=str(save_path),
    )
    return {"file_id": fid, "filename": save_name, "kind": "image", "chars": 0}


def _save_doc_bytes(raw: bytes, prefix: str, ext: str) -> dict:
    """把文档生成得到的字节落盘并入库，返回附件元数据。
    kind 标记为 document，前端 _attach_chips 会把它渲染成可点击下载的 chip。"""
    save_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
    save_path = settings.files_dir / save_name
    save_path.write_bytes(raw)
    fid = db.add_file(
        filename=save_name, kind="document", size=len(raw),
        chars=0, text="", path=str(save_path),
    )
    return {"file_id": fid, "filename": save_name, "kind": "document", "chars": 0}


def _last_user_image_bytes(last_user: dict) -> bytes:
    """取最后一条用户消息携带的第一张图片附件的字节；无则返回 b''。"""
    if not last_user:
        return b""
    for a in (last_user.get("attachments") or []):
        if a.get("kind") == "image" and a.get("file_id"):
            fr = db.get_file(a["file_id"])
            if fr and fr.get("path"):
                try:
                    return Path(fr["path"]).read_bytes()
                except Exception:
                    pass
    return b""


def _image_event_stream(conv: dict, last_user: dict, user_mid: str):
    """图片生成/编辑任务的 SSE 流：start -> token(说明) -> image(附件元数据)
    -> usage -> done。生成结果落盘入库，作为助手消息的图片附件下发。

    与文本流共用前端协议：前端把 token 拼进 buffer 作为助手正文，
    image 事件携带的 attachments 由前端在 finalize 时随助手消息一并落库与展示。
    """

    async def gen():
        def emit(obj):
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        yield emit({"type": "start", "user_message_id": user_mid})
        try:
            prompt = (last_user.get("content") or "").strip() if last_user else ""
            task = conv.get("task")
            if task == "image_edit":
                src = _last_user_image_bytes(last_user)
                if not src:
                    yield emit({"type": "error",
                                "message": "编辑图片需要先上传一张原图：请在输入框点附件按钮上传图片，再描述修改要求。"})
                    return
                if not prompt:
                    yield emit({"type": "error", "message": "请描述你想对图片做的修改，例如“换背景为海边落日”。"})
                    return
                # 画图是同步阻塞调用（requests + 模型推理数秒~数十秒），
                # 放到线程池执行，避免堵塞 asyncio 事件循环导致 SSE 卡死。
                raw = await asyncio.to_thread(edit_image, prompt, src, settings.image_size)
                note = "🖼️ 已按你的要求编辑图片，结果见下方预览（点击可看大图/下载）。"
            else:  # image_gen
                if not prompt:
                    yield emit({"type": "error", "message": "请输入想生成的图片描述，或点击下方提示词模版。"})
                    return
                raw = await asyncio.to_thread(generate_image, prompt, settings.image_size)
                note = "🎨 已生成图片，结果见下方预览（点击可看大图/下载）。"

            att = _save_image_bytes(raw, prefix="edit" if task == "image_edit" else "gen")
            # 说明文字作为助手正文（让前端 buffer 收到它）
            yield emit({"type": "token", "content": note})
            # 生成图作为助手消息的附件下发
            yield emit({"type": "image", "attachments": [att]})
            # 图片任务不产生文本 token：用 image_task 标记，前端据此显示
            # “画图任务·不计文本 token”而非误导性的 0 token。
            yield emit({"type": "usage", "compressed": False, "image_task": True,
                        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            yield emit({"type": "done"})
        except Exception as e:
            yield emit({"type": "error", "message": str(e)})

    return gen()


class ChatRequest(BaseModel):
    conversation_id: str
    query: str = ""
    regenerate: bool = False  # 重新生成：不新增用户消息，复用已有最后一条
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    file_ids: list[str] = []  # 本次随消息上传的文件 id


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
    # 附件元数据：file_id + filename + kind + chars
    attachments_meta = []
    if not req.regenerate and req.file_ids:
        for f in db.get_files(req.file_ids):
            attachments_meta.append({
                "file_id": f["id"], "filename": f["filename"],
                "kind": f["kind"], "chars": f.get("chars", 0),
            })
    user_mid = ""
    if not req.regenerate:
        user_mid = db.add_message(conv["id"], "user", req.query,
                                  attachments=attachments_meta)

    # step02：组装上下文（可能触发压缩）
    messages = db.list_messages(conv["id"])

    # 把“最后一条用户消息”所附文件的正文拼进上下文（重新生成时同样生效）
    last_user = next((m for m in reversed(messages) if m["role"] == "user"), None)

    # ===== 图片生成/编辑任务：走专用画图模型，不走文本对话流 =====
    # 复用同一 /chat 接口与 SSE 协议：start -> token(一句说明) -> usage -> done，
    # 生成结果作为“助手消息的图片附件”下发（前端附件预览直接展示）。
    # 重新生成同样生效：复用 last_user 的 prompt 与（编辑任务的）原图。
    if conv.get("task") in IMAGE_TASKS:
        return StreamingResponse(
            _image_event_stream(conv, last_user, user_mid),
            media_type="text/event-stream",
        )

    if last_user:
        fids = [a.get("file_id") for a in (last_user.get("attachments") or [])
                if a.get("file_id")]
        if fids:
            file_rows = db.get_files(fids)
            aug = "\n\n".join(
                f"【附件：{fr['filename']}】\n{fr['text']}"
                for fr in file_rows if fr.get("text")
            )
            if aug:
                last_user["content"] = (last_user.get("content", "") or "") + "\n\n" + aug

    llm_messages, compressed = await build_llm_messages(conv, messages, threshold, keep_turns)

    # 多模态：把最后一条用户消息携带的图片以 image_url 片段注入 content。
    # 文本附件上文已拼进 content；图片此前被 fr.get("text") 过滤掉、模型根本看不到，
    # 这里转成 OpenAI 多模态格式（content 由字符串变为 [text, image_url, ...]），
    # 视觉模型才能真正"看到"图。在压缩/估算之后做，不影响 token 估算与摘要。
    # 注意：需选用支持视觉的模型，否则 API 会报错并经 error 事件透传给前端。
    if last_user:
        img_fids = [a["file_id"] for a in (last_user.get("attachments") or [])
                    if a.get("kind") == "image" and a.get("file_id")]
        if img_fids:
            img_parts = _image_url_parts(img_fids)
            if img_parts:
                for m in reversed(llm_messages):
                    if m.get("role") == "user":
                        txt = m.get("content") or ""
                        m["content"] = [{"type": "text", "text": txt}, *img_parts]
                        break

    # step03：流式请求大模型并通过 SSE 推给前端
    # ===== 文档自动生成：对支持 Function Calling 的模型注入工具 =====
    # 白名单内模型：追加工具引导 system 消息，并带 tools 调用；模型识别到“生成
    # 文档”意图时返回 tool_calls，event_stream 里累积执行后作为附件下发。
    # 白名单外模型：tools=None，正常对话，不报错、无文档能力。
    use_fc = model in settings.fc_models
    if use_fc:
        llm_messages.append({"role": "system", "content": TOOL_GUIDE})
    tools = tools_for_api() if use_fc else None

    async def event_stream():
        full_text = ""
        usage = None
        # 累积流式 tool_calls：{index: {"id", "name", "arguments"}}
        # 跨 chunk 增量拼接，流结束后统一执行。
        tc_buf: dict[int, dict] = {}
        # 先发 start 事件，回传用户消息 id（供前端回填，支持重生成/编辑）
        yield f"data: {json.dumps({'type': 'start', 'user_message_id': user_mid}, ensure_ascii=False)}\n\n"
        try:
            response = await stream_chat(
                llm_messages, model, temperature, top_p, max_tokens, tools=tools
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
                # 累积 tool_calls（OpenAI 流式协议：按 index 分片增量拼接）
                for tc in (getattr(delta, "tool_calls", None) or []):
                    idx = tc.index if tc.index is not None else 0
                    slot = tc_buf.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn:
                        if fn.name:
                            slot["name"] += fn.name
                        if fn.arguments:
                            slot["arguments"] += fn.arguments
            # step04：若模型调用了文档工具，执行打包 -> 落盘 -> 发 file 附件事件
            if tc_buf:
                for idx in sorted(tc_buf):
                    slot = tc_buf[idx]
                    name = slot["name"]
                    try:
                        args = json.loads(slot["arguments"] or "{}")
                    except json.JSONDecodeError as e:
                        yield f"data: {json.dumps({'type': 'error', 'message': f'文档工具参数解析失败：{e}'}, ensure_ascii=False)}\n\n"
                        continue
                    try:
                        raw, ext, note = await asyncio.to_thread(dispatch_tool, name, args)
                    except Exception as e:
                        yield f"data: {json.dumps({'type': 'error', 'message': f'生成文档失败：{e}'}, ensure_ascii=False)}\n\n"
                        continue
                    prefix = {"generate_word": "doc", "generate_ppt": "ppt",
                              "generate_excel": "xls"}.get(name, "doc")
                    att = _save_doc_bytes(raw, prefix, ext)
                    # 说明文字作为助手正文，让前端 buffer 收到它
                    yield f"data: {json.dumps({'type': 'token', 'content': note}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'file', 'attachments': [att]}, ensure_ascii=False)}\n\n"
            # step05：把 token 用量随 done 事件回传；助手回复由前端在“完成/停止”时
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
