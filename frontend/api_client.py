'''后端 API 客户端：封装所有 requests 调用 + SSE 流式解析。
流式对话用独立线程消费，配合 threading.Event 实现“停止生成”。'''
import json
import queue
import threading
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
import os

# 读取项目根目录的 .env，拿到后端端口
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
BACKEND_PORT = os.getenv("BACKEND_PORT", "8002")
BASE_URL = f"http://127.0.0.1:{BACKEND_PORT}"


# ---------------- 基础工具 ----------------
def _get(path: str, **kwargs):
    r = requests.get(f"{BASE_URL}{path}", timeout=30, **kwargs)
    return r.json()


def _post(path: str, payload: dict = None, **kwargs):
    r = requests.post(f"{BASE_URL}{path}", json=payload, timeout=30, **kwargs)
    return r.json()


def _patch(path: str, payload: dict):
    r = requests.patch(f"{BASE_URL}{path}", json=payload, timeout=30)
    return r.json()


def _delete(path: str):
    r = requests.delete(f"{BASE_URL}{path}", timeout=30)
    return r.json()


def avatar_url(path: str) -> str:
    """把后端返回的头像相对路径拼成完整 URL。"""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return f"{BASE_URL}{path}"


# ---------------- 任务 / 模型 / 偏好 ----------------
def get_tasks():
    return _get("/tasks")["tasks"]


def get_models():
    data = _get("/models")
    return data["models"], data["default"]


def get_prefs():
    return _get("/prefs")["prefs"]


def update_prefs(payload: dict):
    return _patch("/prefs", payload)["prefs"]


def upload_avatar(file_bytes: bytes, filename: str):
    files = {"file": (filename, file_bytes)}
    r = requests.post(f"{BASE_URL}/prefs/avatar", files=files, timeout=30)
    return r.json()


def upload_files(file_objs: list):
    """批量上传文件，返回 [{id,filename,kind,size,chars}, ...]。
    file_objs 为 Streamlit UploadedFile 列表。"""
    if not file_objs:
        return []
    multipart = [("files", (f.name, f.getvalue())) for f in file_objs]
    r = requests.post(f"{BASE_URL}/upload", files=multipart, timeout=60)
    return r.json().get("files", [])


def file_download_url(file_id: str) -> str:
    return f"{BASE_URL}/files/{file_id}"


# ---------------- 会话 ----------------
def list_conversations(search: Optional[str] = None):
    params = {"search": search} if search else None
    return _get("/conversations", params=params)["conversations"]


def get_conversation(cid: str):
    data = _get(f"/conversations/{cid}")
    return data["conversation"], data["messages"]


def create_conversation(task: str, model: str, title: str = "新对话"):
    return _post("/conversations", {"task": task, "model": model, "title": title})


def update_conversation(cid: str, **fields):
    return _patch(f"/conversations/{cid}", fields).get("conversation")


def delete_conversation(cid: str):
    return _delete(f"/conversations/{cid}")


def truncate_messages(cid: str, message_id: str, mode: str = "after"):
    return _post(f"/conversations/{cid}/truncate", {"message_id": message_id, "mode": mode})


def save_message(cid: str, role: str, content: str, tokens: int = 0, model: str = ""):
    return _post(f"/conversations/{cid}/messages",
                 {"role": role, "content": content, "tokens": tokens, "model": model})


def export_conversation(cid: str, fmt: str = "md"):
    return _get(f"/conversations/{cid}/export", params={"format": fmt})


def generate_title(user_msg: str, assistant_msg: str):
    return _post("/chat/title", {"user_msg": user_msg, "assistant_msg": assistant_msg}).get("title", "新对话")


# ---------------- 流式聊天（可中断） ----------------
def stream_chat_threaded(
    conversation_id: str,
    query: str,
    regenerate: bool = False,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
    file_ids: Optional[list] = None,
):
    """启动一个后台线程消费 SSE 流，把事件放入 queue 返回。
    返回 (event_queue, stop_event)。前端在 fragment 中轮询 queue 渲染。"""
    q: "queue.Queue" = queue.Queue()
    stop_event = threading.Event()

    payload = {
        "conversation_id": conversation_id,
        "query": query,
        "regenerate": regenerate,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if top_p is not None:
        payload["top_p"] = top_p
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if file_ids:
        payload["file_ids"] = file_ids

    def consume():
        try:
            resp = requests.post(f"{BASE_URL}/chat", json=payload, stream=True, timeout=300)
            for line in resp.iter_lines(decode_unicode=True):
                if stop_event.is_set():
                    resp.close()
                    q.put({"type": "stopped"})
                    return
                if not line or not line.startswith("data: "):
                    continue
                try:
                    evt = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    continue
                q.put(evt)
                if evt.get("type") in ("done", "error"):
                    return
        except Exception as e:
            q.put({"type": "error", "message": str(e)})

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    return q, stop_event
