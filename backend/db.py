'''SQLite 持久化：用户偏好、会话、消息全部落库，刷新/重启不丢数据。
使用标准库 sqlite3，无需额外安装。每次操作打开独立连接，规避跨线程问题。'''
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import settings


def _now() -> str:
    """统一的时间戳格式（ISO 字符串）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn() -> sqlite3.Connection:
    """打开一个新连接，行以字典形式访问。"""
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")  # 开启外键级联删除
    return conn


def init_db() -> None:
    """建表。IF NOT EXISTS 保证可重复执行。"""
    with get_conn() as conn:
        conn.executescript(
            """
            -- 单用户偏好表（固定一行，id=1）
            CREATE TABLE IF NOT EXISTS prefs (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                nickname TEXT DEFAULT '我',
                avatar_path TEXT DEFAULT '',
                theme TEXT DEFAULT 'minimal',
                default_task TEXT DEFAULT 'daily',
                default_model TEXT DEFAULT '',
                temperature REAL DEFAULT 0.5,
                top_p REAL DEFAULT 0.5,
                max_tokens INTEGER DEFAULT 1024,
                history_keep INTEGER DEFAULT 6,
                compress_threshold INTEGER DEFAULT 3000
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT '新对话',
                task TEXT DEFAULT 'daily',
                model TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                summary_until_msg_id TEXT DEFAULT '',
                pinned INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT,
                role TEXT,
                content TEXT,
                tokens INTEGER DEFAULT 0,
                model TEXT DEFAULT '',
                created_at TEXT,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id);

            -- 确保偏好行存在
            INSERT OR IGNORE INTO prefs (id) VALUES (1);
            """
        )


# ---------------- 偏好 ----------------
def get_prefs() -> dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM prefs WHERE id=1").fetchone()
        return dict(row) if row else {}


def update_prefs(**fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE prefs SET {cols} WHERE id=1", list(fields.values())
        )


# ---------------- 会话 ----------------
def create_conversation(task: str, model: str, title: str = "新对话") -> str:
    cid = uuid.uuid4().hex
    ts = _now()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, task, model, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (cid, title, task, model, ts, ts),
        )
    return cid


def list_conversations(search: Optional[str] = None) -> list[dict]:
    """按更新时间倒序；置顶优先。可按标题/内容关键词搜索。"""
    with get_conn() as conn:
        if search:
            like = f"%{search}%"
            rows = conn.execute(
                """
                SELECT DISTINCT c.* FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.title LIKE ? OR m.content LIKE ?
                ORDER BY c.pinned DESC, c.updated_at DESC
                """,
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM conversations ORDER BY pinned DESC, updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_conversation(cid: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=?", (cid,)).fetchone()
        return dict(row) if row else None


def update_conversation(cid: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE conversations SET {cols} WHERE id=?", [*fields.values(), cid]
        )


def delete_conversation(cid: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM conversations WHERE id=?", (cid,))


# ---------------- 消息 ----------------
def add_message(cid: str, role: str, content: str, tokens: int = 0, model: str = "") -> str:
    mid = uuid.uuid4().hex
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, tokens, model, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (mid, cid, role, content, tokens, model, _now()),
        )
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), cid))
    return mid


def list_messages(cid: str) -> list[dict]:
    """按插入顺序（rowid）返回全部消息，含已被摘要覆盖的历史。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY rowid", (cid,)
        ).fetchall()
        return [dict(r) for r in rows]


def truncate_after(cid: str, msg_id: str) -> None:
    """删除某条消息之后的所有消息（保留 msg_id 本身）。
    用于“重新生成”：保留用户消息，删掉其后的助手回复。"""
    with get_conn() as conn:
        target = conn.execute(
            "SELECT rowid FROM messages WHERE id=?", (msg_id,)
        ).fetchone()
        if not target:
            return
        conn.execute(
            "DELETE FROM messages WHERE conversation_id=? AND rowid > ?",
            (cid, target["rowid"]),
        )


def truncate_from(cid: str, msg_id: str) -> None:
    """删除某条消息及其之后的所有消息（不保留 msg_id）。
    用于“编辑”：删掉旧用户消息及其后的回复，再用新内容重发。"""
    with get_conn() as conn:
        target = conn.execute(
            "SELECT rowid FROM messages WHERE id=?", (msg_id,)
        ).fetchone()
        if not target:
            return
        conn.execute(
            "DELETE FROM messages WHERE conversation_id=? AND rowid >= ?",
            (cid, target["rowid"]),
        )


def set_conversation_summary(cid: str, summary: str, until_msg_id: str) -> None:
    """压缩完成后，记录摘要与“已摘要到哪条消息”。"""
    update_conversation(cid, summary=summary, summary_until_msg_id=until_msg_id)
