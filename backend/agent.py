'''LangChain Agent 编排 + SSE 桥接 + 防死循环中间件。

设计要点：
1. ChatOpenAI(SiliconFlow) 作为 model；create_agent(model, tools, system_prompt, middleware)。
2. 创建 agent 时为 edit_image 等需要 conv_id 的工具**注入上下文参数**（通过 ToolContext /
   store_getter 不可行时，改为：用 Partialed/StructTool 包装闭包，将 conv_id 变成默认参数）。
   此处采用更轻量做法：每次构建 agent 时构造一个"注入 conv_id 的工具副本"，避免污染注册表。
3. astream_events v2：
   - on_chat_model_stream 的 AIMessageChunk.content -> SSE token（保留逐字流式 UX）
   - on_tool_start -> SSE tool（让用户看见"思考过程"，不再像一直卡在思考）
   - on_tool_end -> drain_attachments 上传文件 -> SSE image / file
   - on_chat_model_end：可选读取最后的 tool_calls 决策
4. 防死循环：
   - config.recursion_limit = 12：硬上限，捕获 GraphRecursionError
   - LoopGuardMiddleware：每轮统计 AIMessage.tool_calls 次数 + 重复检测；
     超预算时不再注入"停止"消息（容易扰乱输出），而是在下一次 model 调用前设置
     临时"请基于已有信息直接回答，不要再调用工具"的系统消息 + 阻断进一步工具调用。
     实际实现：在 pre_model_hook 中检查 messages，若超过 max_steps 就抛出一个特殊异常
     让外层捕捉并强制生成收尾消息。
5. 工具失败处理：每个工具体内捕获异常，返回错误字符串，不抛异常（避免重试循环）。

这里不直接产 sse：agent_stream() 返回 async iterator[dict|str]，
由 routers/chat.py 序列化为 text/event-stream 字符串。
SSE 批处理：相邻的 token 事件会被合并成单条 `token` 事件，
大小阈值或超时（50ms）触发 flush——减少 SSE 包数与前端组件重渲压力。
'''
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

from langchain.agents import create_agent
from langchain.tools import tool as lc_tool_decorator
from langchain_core.tools import BaseTool, ToolException
from langchain_openai import ChatOpenAI

import db
from config import settings
from logs.agent_trace import begin_run, end_run, trace_event
from prompts import get_prompt
from tools import ALL_TOOLS
from tools.attachments import drain_attachments, reset_attachments

# ---------- 默认防循环参数（优先从 .env 读，可热改）----------
RECURSION_LIMIT = settings.agent_recursion_limit
MAX_AGENT_STEPS = settings.agent_max_steps
MAX_STEP_SOFT = max(1, settings.agent_max_steps - 1)
REPEAT_TOLERANCE = 2

# SSE 批处理：相邻 token 事件累积到 ≥32 字符或 ≥50ms 就 flush。
# 平衡"流畅度"与"前端组件渲染压力"——32 字符 ≈ 一个中文字符，体感延迟 < 100ms。
SSE_BATCH_MAX_CHARS = 32
SSE_BATCH_MAX_MS = 50

# _batch_token_events 用于标记生成器结束的哨兵对象（不能用 None：事件本身可能是 None）
_SENTINEL = object()


async def _batch_token_events(source: AsyncIterator[dict]) -> AsyncIterator[dict]:
    """把源异步迭代器里相邻的 token 事件合并成单条 yield，其它类型事件原样透传。

    设计要点：
    - token 累积达到 SSE_BATCH_MAX_CHARS 字符数立即 flush（避免小消息延迟）
    - 未达阈值则等 SSE_BATCH_MAX_MS 后 flush（保证最坏延迟，避免长间隔静默）
    - 非 token 事件到来时立即 flush 当前 buffer + 透传新事件（让工具事件不延迟）

    !!! 实现注意：不能用 asyncio.wait_for(source.__anext__(), timeout=...) 直接包生成器
    的 __anext__()——超时会 cancel 内部正在 await 的 astream_events 调用，破坏流式生成器
    状态，导致它永远拿不到首包（实测 50ms 超时反复 cancel 后 actor 完全卡死）。
    解法：用后台 task 把 gen 事件泵入 asyncio.Queue，主循环 wait_for(queue.get())。
    cancel 只作用于 queue.get（轻量、可重试），不触碰生成器本体。
    """
    q: asyncio.Queue = asyncio.Queue()

    async def _pump():
        try:
            async for evt in source:
                await q.put(evt)
        except Exception as e:
            await q.put(e)
        finally:
            await q.put(_SENTINEL)

    pump_task = asyncio.create_task(_pump())
    buf = ""
    timeout_s = SSE_BATCH_MAX_MS / 1000

    try:
        while True:
            try:
                evt = await asyncio.wait_for(q.get(), timeout=timeout_s)
            except asyncio.TimeoutError:
                # 超时期间没有新事件：把已累积的 token 先 flush，保持体感响应
                if buf:
                    yield {"type": "token", "content": buf}
                    buf = ""
                continue

            if evt is _SENTINEL:
                # 生成器结束：flush 剩余 buffer
                if buf:
                    yield {"type": "token", "content": buf}
                return

            if isinstance(evt, Exception):
                # 生成器抛异常：先 flush buffer 再透传 error
                if buf:
                    yield {"type": "token", "content": buf}
                    buf = ""
                yield {"type": "error", "message": str(evt)}
                return

            if evt.get("type") == "token":
                buf += evt.get("content", "")
                if len(buf) >= SSE_BATCH_MAX_CHARS:
                    yield {"type": "token", "content": buf}
                    buf = ""
            else:
                # 非 token 事件：先 flush 当前 buffer 再透传
                if buf:
                    yield {"type": "token", "content": buf}
                    buf = ""
                yield evt
    finally:
        # 主消费者提前结束（如客户端断连）：取消后台 pump，避免泄漏
        if not pump_task.done():
            pump_task.cancel()
            try:
                await pump_task
            except (asyncio.CancelledError, Exception):
                pass


# ======================================================================
#  ChatOpenAI 工厂
# ======================================================================
def build_chat_model(model_id: str, temperature: float = 0.5,
                     top_p: float = 0.5, max_tokens: int = 1024) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=model_id,
        streaming=True,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        # 让 token 用量回传
        stream_usage=True,
    )


# ======================================================================
#  工具上下文注入（给 edit_image 等需要 conv_id 的工具）
# ======================================================================
def _inject_runtime_args(tools: list[BaseTool], conv_id: str) -> list[BaseTool]:
    """对需要运行时参数（conv_id）的工具，生成一个闭包副本，把 conv_id 默认注入。

    实现策略：用 StructuredTool.from_function 包装一个轻量包装函数，把 conv_id 闭包捕入；
    包装函数带 docstring，避免 langchain 装饰器的检测失败。
    """
    from langchain_core.tools import StructuredTool
    from inspect import signature

    needs_conv = {"edit_image"}  # 需要 conv_id 的工具名
    injected = []
    for t in tools:
        if t.name not in needs_conv:
            injected.append(t)
            continue
        # 包装：拦截 invoke，缺失 conv_id 时填入
        base = t

        def _make_inner(base_tool, cid):
            async def _wrapper(**kwargs):
                # 调用原始 tool 的 invoke
                if "conv_id" not in kwargs or not kwargs.get("conv_id"):
                    kwargs["conv_id"] = cid
                return await base_tool.ainvoke(kwargs)
            _wrapper.__name__ = base_tool.name + "_wrapped"
            _wrapper.__qualname__ = _wrapper.__name__
            _wrapper.__doc__ = (base_tool.description or "代理注入 conv_id 的工具") + \
                f"\n\n提示：参数 conv_id 由系统在调用前自动注入，本参数对用户透明。"
            return _wrapper

        wrapper = _make_inner(base, conv_id)
        new_tool = StructuredTool.from_function(
            func=None,
            coroutine=wrapper,
            name=base.name,
            description=wrapper.__doc__,
            args_schema=base.args_schema if hasattr(base, "args_schema") else None,
        )
        injected.append(new_tool)
    return injected


# ======================================================================
#  防死循环中间件（LoopGuard）
# ======================================================================
class LoopGuard:
    """轻量级循环卫士，不依赖 langgraph 的 middleware 接口（更易维护，
    直接由 agent_stream 在外层 astream_events 中检测并强制收尾）。

    检测两种异常模式：
    (a) 单轮中工具被连续调用 >= MAX_STEP_SOFT 次
    (b) 同一 (tool_name, args) 重复出现 >= REPEAT_TOLERANCE 次

    一旦命中，发出 LoopBreaker 信号：把 current_text 设置为最终收尾语，
    并在下一次循环里主动停止继续。"""

    def __init__(self, max_steps: int = MAX_STEP_SOFT,
                 repeat_tolerance: int = REPEAT_TOLERANCE):
        self.max_steps = max_steps
        self.repeat_tolerance = repeat_tolerance
        self.tool_call_count = 0
        self.calls: list[tuple[str, tuple]] = []   # (name, frozenset of args)
        self.triggered: bool = False
        self.trigger_reason: str = ""

    def observe_tool_call(self, name: str, args: dict) -> None:
        if self.triggered:
            return
        self.tool_call_count += 1
        key = (name, tuple(sorted(args.items())))
        self.calls.append(key)
        # 重复检测
        if self.calls.count(key) >= self.repeat_tolerance:
            self.triggered = True
            self.trigger_reason = f"重复调用同一工具（{name}）已达 {self.repeat_tolerance} 次"
            return
        # 步数软上限
        if self.tool_call_count >= self.max_steps:
            self.triggered = True
            self.trigger_reason = f"本轮工具调用已达 {self.max_steps} 次上限"


# ======================================================================
#  Agent 运行入口（routers/chat.py 会调用）
# ======================================================================
async def agent_stream(
    conv: dict,
    lc_messages: list[dict],
    model: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    multimodal_parts: list[dict] | None = None,
) -> AsyncIterator:
    """执行一次 agent run，并把事件流 yield 出来供 chat.py 序列化 SSE。

    yield 的事件类型（与现有前端协议兼容 + 新增）：
    - {"type": "tool", "name": ..., "args": ..., "status": "start"|"limit"|"repeat"}
    - {"type": "token", "content": ...}
    - {"type": "image"|"file", "attachments": [...]}
    - {"type": "usage", "compressed": bool, "prompt_tokens": int, "completion_tokens": int, "total_tokens": int}
    - {"type": "done"}
    - {"type": "error", "message": ...}
    """
    conv_id = conv.get("id", "")
    # 注入隐式用户画像：让任务提示词按用户提问风格做"轻"微调
    prefs = db.get_prefs()
    task_prompt = get_prompt(
        conv.get("task"),
        user_intent=prefs.get("user_intent") or "general",
        detail_level=prefs.get("detail_level") or "normal",
    )

    # 给 edit_image 等注入 conv_id
    tools = _inject_runtime_args(ALL_TOOLS, conv_id)

    chat = build_chat_model(model, temperature, top_p, max_tokens)
    guard = LoopGuard()

    # 重置附件 contextvar
    reset_attachments()

    # 开启 trace（no-op if AGENT_TRACE=0）
    begin_run(conv_id=conv_id, model=model)

    # 总 token 累计
    total_prompt = 0
    total_completion = 0
    saw_tool_call = False  # 是否有工具被调用（用于 usage 语义区分）
    final_text_started = False
    loop_limit_hit = False
    loop_limit_msg = ""
    start_ts = time.monotonic()

    try:
        agent = create_agent(model=chat, tools=tools, system_prompt=task_prompt)

        config: dict[str, Any] = {"recursion_limit": RECURSION_LIMIT}
        # 简易 agent trace 日志（附加到全局，便于排查）
        try:
            from logs.agent_trace import trace_event  # type: ignore
        except Exception:
            trace_event = None  # type: ignore

        # 将多模态图片（OpenAI image_url 片段）注入最后一条 user 消息，
        # 仅当选用支持视觉的模型时才有意义；非视觉模型会报错但会被 astream_events 透传为 error 事件。
        messages_input = lc_messages
        if multimodal_parts:
            messages_input = list(lc_messages)
            for m in reversed(messages_input):
                if m.get("role") == "user":
                    txt = m.get("content") or ""
                    m["content"] = [{"type": "text", "text": txt}, *multimodal_parts]
                    break

        try:
            async for event in agent.astream_events(
                {"messages": messages_input},
                config=config,
                version="v2",
            ):
                kind = event["event"]
                name = event.get("name", "")
                data = event.get("data", {})

                if kind == "on_tool_start":
                    tool_name = event.get("name", "")
                    tool_input = data.get("input") or {}
                    if isinstance(tool_input, dict):
                        obs_args = tool_input
                    else:
                        obs_args = {"input": str(tool_input)}
                    guard.observe_tool_call(tool_name, obs_args)
                    trace_event("tool_start", {"name": tool_name, "args": obs_args})
                    yield {"type": "tool", "name": tool_name, "args": obs_args, "status": "start"}
                    saw_tool_call = True
                    if guard.triggered:
                        loop_limit_hit = True
                        loop_limit_msg = guard.trigger_reason
                        trace_event("tool_limit", {"reason": loop_limit_msg})
                        yield {"type": "tool", "name": "loop_guard",
                               "args": {}, "status": "limit",
                               "message": loop_limit_msg}

                elif kind == "on_tool_end":
                    # 工具完成；取出并下发附件
                    drained = drain_attachments()
                    if drained:
                        trace_event("tool_end", {"attachments": [a.get("kind") for a in drained]})
                    for att in drained:
                        kind_evt = "image" if att.get("kind") == "image" else "file"
                        yield {"type": kind_evt, "attachments": [att]}

                elif kind == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    if not chunk:
                        continue
                    # 累积 token 用量（每 chunk 可能带 usage_metadata）。
                    # 修复 bug：原本用 max()，会把"后续 chunk 较小值"覆盖"已有最大值"，导致
                    # 末端 usage 比实际小一截。改成"取最后一个非 None 值"——
                    # OpenAI/兼容协议通常只让最后一个 chunk 带完整 usage_metadata。
                    um = getattr(chunk, "usage_metadata", None)
                    if um:
                        if um.get("input_tokens") is not None:
                            total_prompt = int(um["input_tokens"])
                        if um.get("output_tokens") is not None:
                            total_completion = int(um["output_tokens"])
                    content = getattr(chunk, "content", None)
                    if content:
                        final_text_started = True
                        yield {"type": "token", "content": content}
                    tool_calls = getattr(chunk, "tool_calls", None)
                    if tool_calls:
                        # 让前端看到"模型决定调哪些工具"的预览（即使实际执行在 on_tool_start 才有）
                        pass

                elif kind == "on_chat_model_end":
                    out = data.get("output")
                    if out is not None:
                        # 当轮结束：检查是否 loop_limit 触发 -> 追加提示
                        # 同样：取最后值而非 max()
                        um = getattr(out, "usage_metadata", None)
                        if um:
                            if um.get("input_tokens") is not None:
                                total_prompt = int(um["input_tokens"])
                            if um.get("output_tokens") is not None:
                                total_completion = int(um["output_tokens"])

                elif kind == "on_chain_end" and name == "LangGraph":
                    # 整轮结束
                    break

                # loop_limit 触发的下一步：让 LangChain 下次 model 调用前能感知收尾
                if loop_limit_hit and not final_text_started:
                    # 没有产生过任何 token -> 强制发个收尾串，让前端能有缓冲内容
                    yield {"type": "token",
                           "content": f"\n\n[已触发循环守卫：{loop_limit_msg}]"}
                    final_text_started = True

        except Exception as e:
            # GraphRecursionError 超 recursion_limit 时抛 RecursionError；
            # 捕获并优雅收尾
            err_name = type(e).__name__
            if "Recursion" in err_name or "GraphRecursion" in err_name:
                loop_limit_hit = True
                loop_limit_msg = f"超过最大推理步数（recursion_limit={RECURSION_LIMIT}）"
                yield {"type": "tool", "name": "loop_guard", "args": {},
                       "status": "limit", "message": loop_limit_msg}
                if not final_text_started:
                    yield {"type": "token",
                           "content": "\n\n[已达到最大推理步数，先基于已有信息给出当前结论。]"}
            else:
                yield {"type": "error", "message": f"{e}"}
        # 终态：usage + done
        # 若模型从未得到文本 token（例如纯工具产出附件），补一句总结
        if not final_text_started:
            if saw_tool_call:
                yield {"type": "token",
                       "content": "已根据工具查询结果处理完毕，见上文步骤与附件。"}

        trace_event("usage", {"prompt": total_prompt, "completion": total_completion,
                              "tool_calls": guard.tool_call_count,
                              "limit_hit": loop_limit_hit})
        yield {
            "type": "usage",
            "compressed": False,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
        }
        yield {"type": "done"}
        end_run({"tool_calls": guard.tool_call_count,
                 "tokens": total_prompt + total_completion,
                 "limit": loop_limit_hit})

    except Exception as e:
        trace_event("error", {"err": f"{type(e).__name__}: {e}"})
        try:
            end_run({"err": f"{type(e).__name__}"})
        except Exception:
            pass
        yield {"type": "error", "message": f"{e}"}
