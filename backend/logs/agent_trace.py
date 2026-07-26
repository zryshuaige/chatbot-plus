"""Agent 运行 trace 落盘（JSONL）。

用途：
- 调优 MAX_AGENT_STEPS / RECURSION_LIMIT 时复盘一次失败 / 循环对话的步骤序列；
- 偶尔排查"为什么这个工具被调了 N 次"；
- 监控 token 用量分布。

设计：
- 单线程顺序写，锁保护；
- 默认写到 logs/agent.jsonl（项目根的 logs/，与 backend.log/frontend.log 同级）；
- 行 = JSON object，一事件一行；
- AGENT_TRACE=0 时直接 no-op，不影响性能。

字段（每行）：
- ts：unix timestamp (float)
- run_id：uuid4.hex（一次 astream_events 调用共享一个 run_id）
- conv_id：对话 id
- model：模型 id
- event：start|token|tool_start|tool_end|tool_limit|usage|done|error|stop
- 其它键由调用方附加，例如 tool/args/tokens/elapsed_ms。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# 锁 + 项目根目录常量
_LOCK = threading.Lock()
_RUN_ID: str | None = None  # 每次 agent_stream() 开始时 set
_RUN_T0: float | None = None

# 项目根 = backend/logs 的上两级 = backend/../   (项目根)
_ROOT = Path(__file__).resolve().parents[2]
_TRACE_PATH = Path(os.environ.get("AGENT_TRACE_PATH", str(_ROOT / "logs" / "agent.jsonl")))
_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _enabled() -> bool:
    """开关：1 启用 / 0 禁用（默认启用）。可通过环境变量覆盖。"""
    val = os.environ.get("AGENT_TRACE", "1").strip()
    return val not in ("0", "false", "False", "no", "")


def begin_run(conv_id: str, model: str) -> str:
    """开始一次 agent run；返回 run_id。"""
    global _RUN_ID, _RUN_T0
    _RUN_ID = uuid.uuid4().hex
    _RUN_T0 = time.monotonic()
    trace_event("start", {"conv_id": conv_id, "model": model})
    return _RUN_ID


def end_run(stats: dict | None = None) -> None:
    """结束一次 agent run（不强制；也可以不调用）。"""
    global _RUN_ID, _RUN_T0
    if _RUN_ID is None:
        return
    elapsed_ms = None
    if _RUN_T0 is not None:
        elapsed_ms = int((time.monotonic() - _RUN_T0) * 1000)
    trace_event("stop", {"elapsed_ms": elapsed_ms, **(stats or {})})
    _RUN_ID = None
    _RUN_T0 = None


def trace_event(event: str, payload: dict | None = None) -> None:
    """落一条事件。"""
    if not _enabled():
        return
    global _RUN_ID
    rec: dict[str, Any] = {
        "ts": round(time.time(), 4),
        "run_id": _RUN_ID,
        "event": event,
    }
    if payload:
        rec.update(payload)
    line = json.dumps(rec, ensure_ascii=False, default=str)
    with _LOCK:
        try:
            with _TRACE_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            # trace 不应让主流程失败；吞掉 IO 异常
            pass


def current_run_id() -> str | None:
    return _RUN_ID


def trace_path() -> Path:
    return _TRACE_PATH
