'''文件上传路由：接收多文件 -> 落盘到 data/files/ -> 抽取文本 -> 入库。
文本类文件（txt/md/py/json/csv/...）抽取正文，聊天时注入上下文；
图片等二进制只记录元数据（按文件名告知模型）。'''
import shutil
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

import db
from config import settings

router = APIRouter()

# 可抽取正文的文本类扩展名
TEXT_EXTS = {
    "txt", "md", "markdown", "rst", "log", "ini", "conf", "cfg", "env",
    "py", "js", "ts", "jsx", "tsx", "java", "c", "h", "cpp", "hpp", "cc",
    "go", "rs", "rb", "php", "swift", "kt", "scala", "sh", "bash", "zsh",
    "sql", "json", "yaml", "yml", "xml", "html", "htm", "css", "scss", "less",
    "csv", "tsv", "toml", "vue", "dart", "lua", "pl", "r", "matlab",
}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"}


def _ext(filename: str) -> str:
    return (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""


def _classify(ext: str) -> str:
    if ext in TEXT_EXTS:
        return "text"
    if ext in IMAGE_EXTS:
        return "image"
    return "other"


def _extract_text(raw: bytes) -> str:
    """尽力解码为文本并截断到阈值，避免撑爆上下文。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gbk", errors="ignore")
        except Exception:
            text = raw.decode("latin-1", errors="ignore")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > settings.max_file_chars:
        text = text[:settings.max_file_chars] + "\n…（已截断，仅保留前部分内容）"
    return text


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    """批量上传文件，返回每个文件的元数据（含抽取到的字符数）。"""
    if not files:
        raise HTTPException(400, "未收到文件")
    results = []
    for f in files:
        ext = _ext(f.filename)
        kind = _classify(ext)
        raw = await f.read()
        if len(raw) > settings.max_file_size:
            raise HTTPException(413, f"文件 {f.filename} 超过大小限制")
        # 落盘（唯一文件名，避免覆盖）
        save_name = f"{uuid.uuid4().hex[:12]}_{f.filename}"
        save_path = settings.files_dir / save_name
        with save_path.open("wb") as fp:
            fp.write(raw)
        # 抽取文本
        text = _extract_text(raw) if kind == "text" else ""
        fid = db.add_file(
            filename=f.filename, kind=kind, size=len(raw),
            chars=len(text), text=text, path=str(save_path),
        )
        results.append({
            "id": fid, "filename": f.filename, "kind": kind,
            "size": len(raw), "chars": len(text),
        })
    return {"code": 200, "files": results}


@router.get("/files/{file_id}")
def download(file_id: str):
    """下载原始文件。"""
    f = db.get_file(file_id)
    if not f:
        raise HTTPException(404, "文件不存在")
    return FileResponse(f["path"], filename=f["filename"])
