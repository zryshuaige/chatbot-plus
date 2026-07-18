'''偏好路由：读写用户偏好（昵称/主题/任务/模型/采样参数/压缩阈值）+ 头像上传。
头像以文件形式存到 data/avatars/，由 main.py 的 StaticFiles 暴露。'''
import shutil
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

import db
from config import settings

router = APIRouter()

ALLOWED_AVATAR_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


@router.get("/prefs")
def get_prefs():
    prefs = db.get_prefs()
    # 没设过默认模型时，回退到 .env
    if not prefs.get("default_model"):
        prefs["default_model"] = settings.default_model
    if not prefs.get("compress_threshold"):
        prefs["compress_threshold"] = settings.compress_threshold
    if not prefs.get("history_keep"):
        prefs["history_keep"] = settings.keep_recent_turns
    return {"code": 200, "prefs": prefs}


@router.patch("/prefs")
def update_prefs(payload: dict):
    # 只允许更新白名单字段，避免越权写
    allowed = {
        "nickname", "avatar_path", "theme", "default_task", "default_model",
        "temperature", "top_p", "max_tokens", "history_keep", "compress_threshold",
    }
    fields = {k: v for k, v in payload.items() if k in allowed}
    db.update_prefs(**fields)
    return {"code": 200, "prefs": db.get_prefs()}


@router.post("/prefs/avatar")
def upload_avatar(file: UploadFile = File(...)):
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_AVATAR_EXT:
        raise HTTPException(400, f"不支持的图片格式，允许：{ALLOWED_AVATAR_EXT}")
    # 每次上传用唯一文件名，确保前端/浏览器不会拿到旧缓存
    save_name = f"avatar_{uuid.uuid4().hex[:8]}.{ext}"
    save_path = settings.avatars_dir / save_name
    with save_path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    # 清理旧头像文件（保留刚保存的这个）
    for old in settings.avatars_dir.glob("avatar_*.*"):
        if old != save_path:
            try:
                old.unlink()
            except OSError:
                pass
    url = f"/avatars/{save_name}"
    db.update_prefs(avatar_path=url)
    return {"code": 200, "avatar_path": url}
