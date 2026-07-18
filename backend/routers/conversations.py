'''会话路由：增删改查、搜索、导出、截断（编辑/重生成用）、任务清单。'''
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

import db
from config import settings
from prompts import tasks_summary
from llm import available_models, models_meta, image_model_names, image_models_meta

router = APIRouter()


# ---------------- 任务 / 模型清单 ----------------
@router.get("/tasks")
def get_tasks():
    return {"code": 200, "tasks": tasks_summary()}


@router.get("/models")
def get_models():
    """返回文本模型列表 + 默认模型 + 各模型元数据（供前端悬停简介），
    以及图片任务专用的两个模型名与其元数据。"""
    models = available_models()
    return {
        "code": 200,
        "models": models,
        "default": settings.default_model,
        "meta": models_meta(models),
        "image_models": image_model_names(),       # {"gen": ..., "edit": ...}
        "image_meta": image_models_meta(),          # {model_id: {...}}
    }


# ---------------- 会话 CRUD ----------------
class CreateRequest(BaseModel):
    task: str = "daily"
    model: str = ""
    title: str = "新对话"


@router.post("/conversations")
def create_conv(req: CreateRequest):
    prefs = db.get_prefs()
    model = req.model or prefs.get("default_model") or settings.default_model
    cid = db.create_conversation(req.task, model, req.title)
    return {"code": 200, "id": cid, "conversation": db.get_conversation(cid)}


@router.get("/conversations")
def list_conv(search: Optional[str] = Query(default=None)):
    return {"code": 200, "conversations": db.list_conversations(search)}


@router.get("/conversations/{cid}")
def get_conv(cid: str):
    conv = db.get_conversation(cid)
    if not conv:
        return {"code": 404, "message": "会话不存在"}
    return {"code": 200, "conversation": conv, "messages": db.list_messages(cid)}


class UpdateRequest(BaseModel):
    title: Optional[str] = None
    task: Optional[str] = None
    model: Optional[str] = None
    pinned: Optional[int] = None


@router.patch("/conversations/{cid}")
def update_conv(cid: str, req: UpdateRequest):
    fields = {k: v for k, v in req.model_dump().items() if v is not None}
    db.update_conversation(cid, **fields)
    return {"code": 200, "conversation": db.get_conversation(cid)}


@router.delete("/conversations/{cid}")
def delete_conv(cid: str):
    db.delete_conversation(cid)
    return {"code": 200, "message": "已删除"}


# ---------------- 截断（编辑 / 重新生成） ----------------
class TruncateRequest(BaseModel):
    message_id: str
    mode: str = "after"  # after: 保留该条删其后（重生成）；from: 删该条及其后（编辑）


@router.post("/conversations/{cid}/truncate")
def truncate_conv(cid: str, req: TruncateRequest):
    if req.mode == "from":
        db.truncate_from(cid, req.message_id)
    else:
        db.truncate_after(cid, req.message_id)
    return {"code": 200, "messages": db.list_messages(cid)}


# ---------------- 追加消息（前端在流式完成/停止后落库助手回复） ----------------
class SaveMessageRequest(BaseModel):
    role: str
    content: str
    tokens: int = 0
    model: str = ""
    attachments: Optional[list] = None  # 助手消息可携带附件（如图片生成结果）


@router.post("/conversations/{cid}/messages")
def save_message(cid: str, req: SaveMessageRequest):
    mid = db.add_message(cid, req.role, req.content, req.tokens, req.model,
                         attachments=req.attachments)
    return {"code": 200, "id": mid, "message": db.list_messages(cid)[-1]}


# ---------------- 导出 ----------------
@router.get("/conversations/{cid}/export")
def export_conv(cid: str, format: str = Query(default="md")):
    conv = db.get_conversation(cid)
    if not conv:
        return {"code": 404, "message": "会话不存在"}
    messages = db.list_messages(cid)
    if format == "json":
        payload = json.dumps(
            {"conversation": conv, "messages": messages},
            ensure_ascii=False, indent=2,
        )
        return {"code": 200, "format": "json", "content": payload}
    # markdown
    lines = [f"# {conv['title']}", ""]
    role_label = {"user": "🧑 用户", "assistant": "🤖 助手", "system": "系统"}
    for m in messages:
        lines.append(f"### {role_label.get(m['role'], m['role'])}")
        lines.append("")
        lines.append(m["content"])
        lines.append("")
    return {"code": 200, "format": "md", "content": "\n".join(lines),
            "filename": f"{conv['title']}-{datetime.now().strftime('%Y%m%d')}.md"}
