"""图片生成 / 编辑工具：把原 llm.py 的 generate_image / edit_image 改造为 langchain 工具。

改造后：图片能力成为“普通对话中模型可随时调用的工具”，不再只能切到“图片生成/编辑”任务模式。
- generate_image：纯文生图；
- edit_image：图生图，取最近一条用户消息携带的图片附件作为原图（通过 conv_id 查 DB），
  无图则返回提示串让模型转告用户上传。
工具内调 llm.generate_image/edit_image（现有逻辑），落盘入库 -> push_attachment -> 返回说明串。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from langchain.tools import tool

from config import settings
import db
import llm
from .attachments import push_attachment


def _save_image(raw: bytes, prefix: str = "gen") -> dict:
    """复用与 chat.py 一致的图片落盘逻辑，返回附件元数据。"""
    ext = "png"
    try:
        from PIL import Image
        from io import BytesIO
        fmt = Image.open(BytesIO(raw)).format or ""
        ext = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif",
               "BMP": "bmp"}.get(fmt.upper(), "png")
    except Exception:
        ext = "png"
    save_name = f"{prefix}_{uuid.uuid4().hex[:12]}.{ext}"
    save_path = settings.files_dir / save_name
    save_path.write_bytes(raw)
    fid = db.add_file(filename=save_name, kind="image", size=len(raw),
                      chars=0, text="", path=str(save_path))
    return {"file_id": fid, "filename": save_name, "kind": "image", "chars": 0}


def _last_user_image_bytes(conv_id: str) -> bytes:
    """取本会话最近一条用户消息携带的第一张图片附件字节。无则返回 b''。"""
    messages = db.list_messages(conv_id)
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        for a in (m.get("attachments") or []):
            if a.get("kind") == "image" and a.get("file_id"):
                fr = db.get_file(a["file_id"])
                if fr and fr.get("path"):
                    try:
                        return Path(fr["path"]).read_bytes()
                    except Exception:
                        pass
    return b""


@tool
def generate_image(prompt: str) -> str:
    """根据文字描述生成图片（文生图）。已落库，结果以图片附件形式下发。
    适合用户要在普通对话中“画一张 / 生成一张图 / 画个 XX”，而无需切换到专门的画图任务。

    鼓励详细描述主体、环境、光线、风格、构图，描述越具体出图越精准。

    Args:
        prompt: 图片描述（中文或英文均可），如“赛博朋克都市夜景，霓虹招牌，雨后倒影，电影感”。
    """
    desc = (prompt or "").strip()
    if not desc:
        return "生成失败：请提供图片描述，例如“画一只戴墨镜的猫，油画风格”。"
    try:
        raw = llm.generate_image(desc, settings.image_size)
    except Exception as e:
        return f"生成失败：图片生成出错（{e}）。"
    att = _save_image(raw, prefix="gen")
    push_attachment(att)
    return f"🎨 已按描述生成图片，见下方附件预览（可点击看大图/下载）。"


@tool
def edit_image(prompt: str, conv_id: str = "") -> str:
    """对用户上传的原图按要求进行编辑（图生图：换背景/改风格/加删元素/调光影/加文字等）。
    结果以图片附件形式下发。自动使用本会话最近上传的图片作为原图。

    若本会话尚未上传图片，返回提示--模型应转告用户先上传原图再描述修改要求。

    Args:
        prompt: 对图片的修改要求，如“把背景换成海边落日”“转为动漫风格”。
        conv_id: 当前会话 id（由系统自动注入，用于定位最近上传的原图）。
    """
    desc = (prompt or "").strip()
    if not desc:
        return "编辑失败：请描述想对图片做的修改，例如“换背景为海边落日”。"
    src = _last_user_image_bytes(conv_id) if conv_id else b""
    if not src:
        return ("编辑失败：本会话还没有上传原图。请转告用户：在输入框点附件按钮上传一张图片，"
                "再描述修改要求。")
    try:
        raw = llm.edit_image(desc, src, settings.image_size)
    except Exception as e:
        return f"编辑失败：图片编辑出错（{e}）。"
    att = _save_image(raw, prefix="edit")
    push_attachment(att)
    return f"🖼️ 已按要求编辑图片，结果见下方附件预览（可点击看大图/下载）。"


IMAGE_TOOLS = [generate_image, edit_image]
