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
# 统一错误处理：HTTP 4xx/5xx 与连接异常都返回 {"code":-1, "message":...}，
# 避免后端 500 时前端 KeyError 红屏。调用方仍需检查 `code` 字段。
def _safe_json(r: requests.Response) -> dict:
    """把 Response 解析成 dict；非 JSON / 非 2xx 都归一为错误结构。"""
    try:
        data = r.json()
    except ValueError:
        text = (r.text or "")[:200]
        return {"code": r.status_code or -1, "message": f"后端返回非 JSON：{text}"}
    if r.status_code >= 400:
        # FastAPI HTTPException 形如 {"detail": "..."}；其他框架各异
        msg = data.get("detail") or data.get("message") or r.text[:200]
        return {"code": r.status_code, "message": str(msg)}
    return data


def _get(path: str, **kwargs):
    try:
        r = requests.get(f"{BASE_URL}{path}", timeout=30, **kwargs)
    except requests.exceptions.RequestException as e:
        return {"code": -1, "message": f"无法连接后端（{BASE_URL}）：{e}"}
    return _safe_json(r)


def _post(path: str, payload: dict = None, **kwargs):
    try:
        r = requests.post(f"{BASE_URL}{path}", json=payload, timeout=30, **kwargs)
    except requests.exceptions.RequestException as e:
        return {"code": -1, "message": f"无法连接后端（{BASE_URL}）：{e}"}
    return _safe_json(r)


def _patch(path: str, payload: dict):
    try:
        r = requests.patch(f"{BASE_URL}{path}", json=payload, timeout=30)
    except requests.exceptions.RequestException as e:
        return {"code": -1, "message": f"无法连接后端（{BASE_URL}）：{e}"}
    return _safe_json(r)


def _delete(path: str):
    try:
        r = requests.delete(f"{BASE_URL}{path}", timeout=30)
    except requests.exceptions.RequestException as e:
        return {"code": -1, "message": f"无法连接后端（{BASE_URL}）：{e}"}
    return _safe_json(r)


def avatar_url(path: str) -> str:
    """把后端返回的头像相对路径拼成完整 URL。"""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return f"{BASE_URL}{path}"


# ---------------- 任务 / 模型 / 偏好 ----------------
def get_tasks():
    """任务列表。返回 list；后端故障时返回空 list（不抛异常）。"""
    try:
        data = _get("/tasks")
        if isinstance(data, dict) and data.get("code") == -1:
            return []
        return (data or {}).get("tasks", []) if isinstance(data, dict) else []
    except Exception:
        return []


def get_models():
    """返回 /models 完整载荷：models/default/meta(文本模型元数据)/
    image_models{gen,edit}/image_meta。前端用 meta 做悬停简介。
    失败时返回空 dict，调用方据此判断。"""
    try:
        data = _get("/models")
        if isinstance(data, dict) and data.get("code") == -1:
            return {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_prefs():
    """用户偏好 dict。后端故障返回 {}。"""
    try:
        data = _get("/prefs")
        if isinstance(data, dict) and data.get("code") == -1:
            return {}
        return (data or {}).get("prefs", {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_tool_groups():
    """获取工具分组（输入区上方 chips 用）。返回 [{key,name,icon,hint,tools}, ...]，
    失败时回退到空 list——chips 区域会直接隐藏，不阻塞主对话流。"""
    try:
        data = _get("/tools")
        return (data or {}).get("groups", []) or []
    except Exception:
        return []


def update_prefs(payload: dict):
    return _patch("/prefs", payload).get("prefs", {})


def reset_profile():
    """重置隐式用户画像（intent + detail_level 回默认）。"""
    return _post("/prefs/profile/reset", {}).get("prefs", {})


def upload_avatar(file_bytes: bytes, filename: str):
    """上传头像。失败时返回 {"code": -1, "message": ...} 包络，与 _safe_json 一致。

    后端成功时返回 {"code": 200, "avatar_path": ...}；前端拿到的是这个 dict。
    """
    files = {"file": (filename, file_bytes)}
    try:
        r = requests.post(f"{BASE_URL}/prefs/avatar", files=files, timeout=30)
    except requests.exceptions.RequestException as e:
        return {"code": -1, "message": f"无法连接后端（{BASE_URL}）：{e}"}
    return _safe_json(r)


def upload_files(file_objs: list):
    """批量上传文件，返回 [{id,filename,kind,size,chars}, ...]。
    file_objs 为 Streamlit UploadedFile 列表。
    失败时返回 {"code": -1, "message": ...} 包络——避免 5xx 时前端 KeyError 红屏。"""
    if not file_objs:
        return []
    multipart = [("files", (f.name, f.getvalue())) for f in file_objs]
    try:
        r = requests.post(f"{BASE_URL}/upload", files=multipart, timeout=60)
    except requests.exceptions.RequestException as e:
        return {"code": -1, "message": f"无法连接后端（{BASE_URL}）：{e}"}
    data = _safe_json(r)
    if isinstance(data, dict) and data.get("code") in (-1, None):
        return data          # 错误：直接返回包络，调用方按 data.get("files", []) 兜底
    return data.get("files", []) if isinstance(data, dict) else []


def upload_files_envelope(file_objs: list):
    """与 upload_files 行为一致但**保留 envelope**：用于要在错误时区分「真失败 vs 0 文件」。
    返回 {} 表示正常包装，{"code": -1, ...} 表示失败。"""
    if not file_objs:
        return {"files": []}
    multipart = [("files", (f.name, f.getvalue())) for f in file_objs]
    try:
        r = requests.post(f"{BASE_URL}/upload", files=multipart, timeout=60)
    except requests.exceptions.RequestException as e:
        return {"code": -1, "message": f"无法连接后端（{BASE_URL}）：{e}"}
    return _safe_json(r)


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


def save_message(cid: str, role: str, content: str, tokens: int = 0,
                 model: str = "", attachments: Optional[list] = None):
    """落库一条消息。attachments 可选，用于助手消息携带图片生成结果等附件。"""
    payload = {"role": role, "content": content, "tokens": tokens, "model": model}
    if attachments is not None:
        payload["attachments"] = attachments
    return _post(f"/conversations/{cid}/messages", payload)


def export_conversation(cid: str, fmt: str = "md"):
    return _get(f"/conversations/{cid}/export", params={"format": fmt})


def generate_title(user_msg: str, assistant_msg: str) -> str:
    """调用 /chat/title；失败时抛 RuntimeError 让前端 toast + 暴露重试。
    成功返回真实标题；不再回退占位符「新对话」——空/占位=失败。"""
    data = _post("/chat/title", {"user_msg": user_msg, "assistant_msg": assistant_msg})
    if not isinstance(data, dict):
        raise RuntimeError(f"标题接口返回异常：{data!r}")
    if data.get("code") not in (200, None):
        msg = data.get("message") or data.get("detail") or "标题生成失败"
        raise RuntimeError(str(msg))
    title = (data.get("title") or "").strip()
    if not title or title == "新对话":
        raise RuntimeError("模型返回为空或占位符")
    return title


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
