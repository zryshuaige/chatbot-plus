"""Tool attachment side-channel (push from tools, drain from agent.py).
Background: langchain tool return values must be strings (becoming ToolMessage.content
fed back to the model), but image / QR / Word / PPT / Excel tools produce FILES that
need to be surfaced as attachments in the frontend.

Implementation: threading.Lock + per-request UUID token isolation.
- agent_stream() calls reset_attachments() at the start -> sets token and clears buffer
- File-producing tools: save to disk -> db.add_file -> push_attachment({...}, token)
- agent.py on on_tool_end -> drain_attachments() -> emit image / file SSE

Why not contextvars: langchain tool execution may run in a separate contextvars.copy_context,
so push and drain would not see the same buffer. A global Lock + token is the most robust.
"""
from __future__ import annotations

import itertools
import threading
import uuid
from typing import Any

_active_token: str | None = None
_pending: list[dict] = []
_lock = threading.Lock()


def reset_attachments() -> str:
    """Reset buffer at the start of each agent run. Returns the request token."""
    global _active_token
    with _lock:
        _active_token = uuid.uuid4().hex
        _pending.clear()
        return _active_token


def push_attachment(meta: dict, token: str | None = None) -> None:
    """Push a file attachment from a tool. If token provided, must match the active run."""
    with _lock:
        if token is None or token == _active_token:
            _pending.append(meta)


def drain_attachments() -> list[dict]:
    """Drain all pending attachments (FIFO) and clear the buffer. agent.py calls this
    on every on_tool_end event to surface files produced by tools."""
    with _lock:
        lst = list(_pending)
        _pending.clear()
        return lst


def current_attachments() -> list[dict]:
    """Read-only view of the buffer (debug)."""
    with _lock:
        return list(_pending)


def get_active_token() -> str | None:
    return _active_token


def size() -> int:
    with _lock:
        return len(_pending)
