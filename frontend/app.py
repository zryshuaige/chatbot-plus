'''chatbot-plus 前端：Streamlit 多轮聊天应用。
特性：任务系统提示词、头像、主题、历史自动命名、上下文压缩、
流式可中断、重生成/编辑、多模型+token用量、会话搜索/导出。'''
import concurrent.futures
from datetime import timedelta

import html
import json
import queue
import streamlit as st
import streamlit.components.v1 as components

import api_client as api
from themes import theme_css, theme_keys, theme_name, DEFAULT_THEME
from render import render_content, user_bubble_html, attachments_html, _normalize_attachments as _coerce_atts
from components.stream_iframe import render_stream_iframe

# 流式渲染模式：True = iframe（marked.js + 0 rerun + 无闪烁）；False = 原 fragment 方案
#
# Block C（chatbot-plus 优化）后重新启用：
# 1. backend_url 现在强制只读注入，禁止回退到 window.parent.location.origin
#    （修复了原"iframe 内 fetch 失败、回退到 Streamlit 自身 8502 端口"的根因）
# 2. streaming_fragment 在 iframe 模式下只做完成探测（1.5s tick），
#    不重建 chat_message → 真正的零闪烁
USE_IFRAME_STREAM = True

st.set_page_config(page_title="chatbot-plus", page_icon="🤖", layout="wide",
                   initial_sidebar_state="auto")  # auto 让移动端默认收起侧边栏，桌面端仍展开


# ================ 注入脚本（经 components.html 在 allow-same-origin 的 iframe 执行，
# 操作 window.parent 即主应用文档）================
# 说明：st.html 会用 DOMPurify 清掉 <script>，JS 根本不执行；st.markdown 会清掉 on* 事件。
# 唯一能在主文档跑 JS 的途径是 components.html（iframe 带 allow-scripts + allow-same-origin）。
# 现在 chips 已改为 CSS-only sticky 钉底（见 themes.py .cp-toolbar），无需 JS 测量。
# 剩下还需要 JS 做的一件事：给灵感按钮打卡片样式（CSS 选择器搞不定文本→class 映射）。
_SUGG_ICONS = ["💡", "✍️", "🧠", "🚀"]


def _cp_components_js(sugg: list) -> str:
    """返回注入主文档的脚本。sugg=当前灵感问题列表（用于给灵感按钮打卡片样式）。

    仅做两件事：
    1. 隐藏自身 iframe（不占版面）
    2. 按文本匹配给灵感按钮加 cp-sugg-card 样式 + 图标

    流式/复制/dock chips 相关逻辑已全部删除。
    """
    sugg_json = json.dumps(sugg or [], ensure_ascii=False)
    icons_json = json.dumps(_SUGG_ICONS, ensure_ascii=False)
    sugg_hash = hash(tuple(sugg or []))
    return f"""<script>
(function(){{
  var w = window.parent, d = w.document;
  // 隐藏自身 iframe（仅用于执行 JS，不占版面）
  try {{
    var f = window.frameElement;
    if (f) {{
      f.style.height = '0'; f.style.width = '0'; f.style.border = '0';
      f.style.position = 'absolute';
      var p = f.parentElement;
      if (p) {{ p.style.height = '0'; p.style.margin = '0'; p.style.padding = '0'; p.style.overflow = 'hidden'; }}
    }}
  }} catch (e) {{}}

  // ---- 灵感卡片：按文本匹配给按钮加卡片样式 + 图标 ----
  function tagSuggestions(list, icons){{
    if (!list || !list.length) return;
    d.querySelectorAll('button').forEach(function (b){{
      var idx = list.indexOf(b.textContent.trim());
      if (idx === -1) return;
      b.classList.add('cp-sugg-card');
      if (!b.querySelector('.cp-sugg-ic')) {{
        b.insertAdjacentHTML('afterbegin', '<span class="cp-sugg-ic">' + (icons[idx % icons.length] || '💡') + '</span>');
      }}
    }});
  }}

  // 注入本轮的灵感列表并立刻打标签（脚本每次 rerun 都执行一次）
  w.__cpSugg = {sugg_json};
  w.__cpSuggIcons = {icons_json};
  w.__cpSuggHash = {sugg_hash};
  tagSuggestions(w.__cpSugg, w.__cpSuggIcons);

  // ---- 监听流式 iframe 上报事件（一次性注册）----
  // iframe 已自行处理 stop（sseAbort.abort + 保存已产出）。父页面仅接收 error/done 提示。
  if (!w.__cpStreamListenerReady) {{
    w.__cpStreamListenerReady = true;
    w.addEventListener('message', function(ev){{
      try {{
        if (!ev.data || typeof ev.data !== 'object') return;
        var t = ev.data.type || '';
        if (t === 'cp-stream-error' || t === 'cp-stream-stopped') {{
          console.info('[cp-stream-iframe]', t, ev.data.error || ev.data);
        }}
        // cp-stream-done 在父页面 streaming_fragment 的轮询路径里检测到，省事不处理
      }} catch (_) {{}}
    }});
  }}
}})();
</script>"""


# ================ 会话状态初始化 ================
def init_state():
    defaults = {
        "prefs": None,
        "tasks": [],
        "models": [],
        "default_model": "",
        "model_meta": {},        # {model_id: {vendor,context,multimodal,tags,price,desc}}
        "image_models": {},      # {"gen": ..., "edit": ...} 图片任务专用画图模型名
        "image_meta": {},        # {image_model_id: {...}} 图片模型元数据
        "current_cid": None,
        "current_title": "",
        "current_model": "",
        "current_task": "daily",
        "messages": [],            # 本地展示用：[{id,role,content,tokens,model}]
        "streaming": False,
        "stream_queue": None,
        "stop_event": None,
        "stream_buffer": "",
        "stream_usage": None,
        "stream_error": None,
        "stream_model": "",
        "stream_attachments": [],   # 图片任务：助手消息携带的图片附件（由 image 事件下发）
        "stream_tool_steps": [],   # agent 工具调用步骤：[{name, args, status, message?}]，气泡上方展示
        "last_usage": None,        # 最近一次 token 用量（展示）
        "editing_msg_id": None,    # 正在编辑的用户消息 id
        "prefs_loaded": False,
        "new_task": "daily",       # 侧边栏"新建对话"用的任务
        "new_model": "",
        "suggestions": [],          # 空会话时展示的随机提示问题
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# ================ 空会话的随机提示 ================
_SUGGESTION_POOL = [
    "用三句话向我解释什么是量子纠缠",
    "帮我写一封礼貌的请假邮件",
    "给我讲一个关于程序员的冷笑话",
    "如何用 Python 实现一个简单的待办清单？",
    "推荐三本适合入门心理学的好书",
    "把这段话润色得更专业一些：我想请假",
    "帮我规划一个周末两天的杭州行程",
    "用大白话解释什么是大语言模型",
    "给我一个 30 分钟的居家健身计划",
    "写一首关于秋天的现代诗",
    "如何高效地背单词？给我一个方法",
    "比较一下 React 和 Vue 的主要区别",
    "给我讲个适合睡前听的小故事",
    "如何回复面试官'你最大的缺点是什么'？",
    "用 5 个成语形容一个人很努力",
    "帮我起三个文艺风的咖啡店名字",
]


def pick_suggestions(n: int = 4) -> list:
    import random
    return random.sample(_SUGGESTION_POOL, min(n, len(_SUGGESTION_POOL)))


def send_suggestion(text: str):
    """点击灵感问题：直接创建会话并发送。"""
    ensure_conversation()
    start_streaming(text, regenerate=False)


def _current_task_obj():
    """当前任务对象：有会话用 current_task；未建会话（current_cid 为空）用 new_task，
    这样在侧边栏选了图片任务但还没发送时，空会话页就能正确显示提示词模版、隐藏通用欢迎语。"""
    if st.session_state.current_cid:
        key = st.session_state.current_task
    else:
        key = st.session_state.new_task or st.session_state.current_task
    return next((t for t in st.session_state.tasks if t["key"] == key), None)


def _is_image_task() -> bool:
    t = _current_task_obj()
    return bool(t and t.get("model") in ("image_gen", "image_edit"))


def _model_id_for_task(task_key: str, text_model: str = "") -> str:
    """任务 -> 实际使用的模型 id。图片任务用专用画图模型，否则用传入的文本模型。
    用于：start_streaming 设置 stream_model、侧边栏显示当前任务所用模型。"""
    if task_key == "image_gen":
        return st.session_state.image_models.get("gen") or text_model
    if task_key == "image_edit":
        return st.session_state.image_models.get("edit") or text_model
    return text_model


# ==================== 工具步骤展示 ====================
def _format_tool_args(args: dict) -> str:
    """把工具入参 dict 渲染成简短的可读字符串。"""
    if not args:
        return ""
    parts = []
    for k, v in list(args.items())[:3]:
        v_str = str(v)
        if len(v_str) > 60:
            v_str = v_str[:60] + "…"
        parts.append(f"{k}={v_str}")
    return ", ".join(parts)


def render_tool_steps(steps: list) -> None:
    """把 agent 的工具调用步骤渲染成一段 HTML，挂在助手气泡上方。
    设计要点：步骤透明 + 折叠（不挤占主回复空间）+ 守卫提示用醒目颜色。
    """
    if not steps:
        return
    import html as _html
    rows = []
    for s in steps:
        name = _html.escape(str(s.get("name") or ""))
        args = _html.escape(_format_tool_args(s.get("args") or {}))
        status = str(s.get("status") or "start")
        msg = _html.escape(str(s.get("message") or ""))
        if status == "start":
            icon, cls = "🔧", "cp-step"
            label = args or "运行中…"
        elif status == "limit":
            icon, cls = "⛔", "cp-step cp-step-warn"
            label = msg or "循环守卫触发"
        elif status == "repeat":
            icon, cls = "🔁", "cp-step cp-step-warn"
            label = msg or "重复调用触发"
        else:
            icon, cls = "•", "cp-step"
            label = args or status
        rows.append(f'<li class="{cls}"><span class="cp-step-icon">{icon}</span>'
                    f'<code class="cp-step-name">{name}</code>'
                    f'<span class="cp-step-args">{label}</span></li>')
    html = (
        '<details class="cp-tool-steps" open>'
        '<summary><b>思考步骤</b>'
        f'<span class="cp-step-count">{len(steps)}</span></summary>'
        f'<ul class="cp-step-list">{"".join(rows)}</ul>'
        '</details>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_model_info(model_id, meta_map=None):
    """渲染模型简介 caption：上下文长度 / 是否多模态 / 特色 / 价格。
    详细描述放在 selectbox 的 help（悬停）里，这里只展示结构化要点。"""
    meta_map = meta_map if meta_map is not None else st.session_state.model_meta
    m = (meta_map or {}).get(model_id)
    if not m:
        st.caption(f"📌 {model_id}（暂无简介）")
        return
    parts = []
    if m.get("context") and m["context"] != "-":
        parts.append(f"📏 {m['context']}")
    parts.append("🖼️ 多模态" if m.get("multimodal") else "📝 文本")
    if m.get("tags"):
        parts.append("✨ " + "/".join(m["tags"]))
    if m.get("price") and m["price"] != "-":
        parts.append(f"💰 {m['price']}")
    st.caption(" · ".join(parts))


def send_template(text: str):
    """点击提示词模版：创建会话并发送（与 send_suggestion 同路径）。"""
    ensure_conversation()
    start_streaming(text, regenerate=False)


def load_meta():
    """首次加载偏好/任务/模型。后端离线时给红 banner + 重试按钮，不再红屏。

    性能优化：3 次 HTTP 用 ThreadPoolExecutor 并发，单次失败不阻断其他，
    全部失败时整体抛错。"""
    if st.session_state.prefs_loaded:
        return
    # 首次加载时显示骨架屏，避免几秒钟的"白屏 / 无元素"
    if not st.session_state.get("_meta_skeleton_shown"):
        with st.spinner("加载中…"):
            st.session_state["_meta_skeleton_shown"] = True

    # 并发拉：偏好/任务/模型 3 个独立请求，理论上 ≤ 1× RTT 完成。
    # 任何一项返回 None 表示该次失败（不抛异常的 degrade 默认值）。
    err_parts: list[str] = []

    def _safe(label, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            err_parts.append(f"{label}: {e}")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=3, thread_name_prefix="meta") as ex:
        f_prefs = ex.submit(_safe, "prefs", api.get_prefs)
        f_tasks = ex.submit(_safe, "tasks", api.get_tasks)
        f_models = ex.submit(_safe, "models", api.get_models)
        prefs_data = f_prefs.result()
        tasks_data = f_tasks.result()
        m = f_models.result()

    # 单项检查 + 单独降级
    if not isinstance(prefs_data, dict) or prefs_data.get("code") == -1:
        msg = (prefs_data.get("message") if isinstance(prefs_data, dict) else None) or "无法连接后端"
        # prefs 失败 → 整页停（其他都需要 prefs）
        st.session_state["_backend_error"] = msg
        return
    st.session_state.prefs = prefs_data

    # tasks/models 各自 fallback：失败用上一轮的本地状态（首次冷启动就是空 list）
    if isinstance(tasks_data, list):
        st.session_state.tasks = tasks_data
    else:
        err_parts.append("任务列表获取失败")

    if isinstance(m, dict):
        st.session_state.models = m.get("models", [])
        st.session_state.default_model = m.get("default", "")
        st.session_state.model_meta = m.get("meta", {})
        st.session_state.image_models = m.get("image_models", {})
        st.session_state.image_meta = m.get("image_meta", {})
    else:
        err_parts.append("模型列表获取失败")

    if not st.session_state.new_model:
        st.session_state.new_model = (st.session_state.prefs.get("default_model")
                                      or st.session_state.default_model)
    st.session_state.prefs_loaded = True
    if err_parts:
        # 部分加载成功：不弹红 banner，但 toast 提示用户某几项失败
        st.session_state["_partial_meta_warn"] = "；".join(err_parts)
        print(f"[load_meta] partial: {err_parts}")
    st.session_state["_backend_error"] = None


load_meta()

# 后端连接失败时：顶部红 banner 阻断后续渲染，避免用户在空数据上乱点
if st.session_state.get("_backend_error"):
    st.error(f"⚠️ 无法连接后端：{st.session_state['_backend_error']}")
    st.caption(f"检查后端是否启动：访问 {api.BASE_URL} 应返回 200")
    if st.button("🔄 重试", key="retry_load_meta", type="primary"):
        st.session_state["prefs_loaded"] = False
        st.session_state["_backend_error"] = None
        st.rerun()
    st.stop()

prefs = st.session_state.prefs
if not st.session_state.suggestions:
    st.session_state.suggestions = pick_suggestions()

# 应用主题
st.markdown(theme_css(prefs.get("theme") or DEFAULT_THEME), unsafe_allow_html=True)


# ================ 通用动作 ================
def switch_conversation(cid: str):
    conv, msgs = api.get_conversation(cid)
    st.session_state.current_cid = cid
    st.session_state.current_title = conv.get("title", "新对话")
    st.session_state.current_model = conv.get("model") or st.session_state.default_model
    st.session_state.current_task = conv.get("task", "daily")
    st.session_state.messages = [
        {"id": m["id"], "role": m["role"], "content": m["content"],
         "tokens": m.get("tokens", 0), "model": m.get("model", ""),
         "attachments": _coerce_atts(m.get("attachments"))}
        for m in msgs
    ]
    st.session_state.editing_msg_id = None
    st.session_state.streaming = False
    # 切会话时清掉重试/重命名相关临时态
    st.session_state["_show_title_retry"] = False
    st.session_state["_title_retry_cid"] = None
    st.session_state["_retry_text"] = None
    st.session_state.pop("_retry_text_input", None)


def ensure_conversation():
    """首次发送时若无会话则自动创建（不 rerun，避免丢失输入文本）。"""
    if st.session_state.current_cid:
        return
    task = st.session_state.new_task
    model = st.session_state.new_model or prefs.get("default_model") or st.session_state.default_model
    data = api.create_conversation(task, model)
    st.session_state.current_cid = data["id"]
    st.session_state.current_title = "新对话"
    st.session_state.current_model = model
    st.session_state.current_task = task
    st.session_state.messages = []


def new_conversation():
    # 不立即创建空会话：仅重置为空白状态，待首次发送时由 ensure_conversation 创建。
    # 这样"历史会话"里不会残留没有任何内容的会话。
    st.session_state.current_cid = None
    st.session_state.current_title = ""
    st.session_state.current_model = (st.session_state.new_model
                                      or prefs.get("default_model")
                                      or st.session_state.default_model)
    st.session_state.current_task = st.session_state.new_task
    st.session_state.messages = []
    st.session_state.editing_msg_id = None
    st.session_state.streaming = False
    st.session_state.last_usage = None
    st.session_state.suggestions = pick_suggestions()
    # 清理与上一会话相关的临时状态
    st.session_state["_show_title_retry"] = False
    st.session_state["_title_retry_cid"] = None
    st.session_state["_retry_text"] = None
    st.session_state.pop("_retry_text_input", None)
    st.rerun()


def task_name(key: str) -> str:
    for t in st.session_state.tasks:
        if t["key"] == key:
            return f"{t['icon']} {t['name']}"
    return key


def _task_icon(key: str) -> str:
    for t in st.session_state.tasks:
        if t["key"] == key:
            return t.get("icon", "💬")
    return "💬"


def _rel_time(ts: str) -> str:
    """把 'YYYY-MM-DD HH:MM:SS' 转成「刚刚 / X 分钟前 / X 天前 / MM-DD」。"""
    from datetime import datetime
    if not ts:
        return ""
    try:
        t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ""
    s = (datetime.now() - t).total_seconds()
    if s < 60:
        return "刚刚"
    if s < 3600:
        return f"{int(s // 60)} 分钟前"
    if s < 86400:
        return f"{int(s // 3600)} 小时前"
    if s < 86400 * 7:
        return f"{int(s // 86400)} 天前"
    return t.strftime("%m-%d")


def maybe_auto_name():
    """首轮问答结束后让 AI 整理标题（自动路径）。
    成功 → toast 提示 + 同步顶栏；失败 → toast 提示 + 暴露「再试一次」按钮。"""
    cid = st.session_state.current_cid
    if not cid:
        return
    if st.session_state.current_title and st.session_state.current_title != "新对话":
        return
    msgs = st.session_state.messages
    if len(msgs) < 2:
        return
    user_msg = next((m for m in msgs if m["role"] == "user"), None)
    asst_msg = next((m for m in msgs if m["role"] == "assistant"), None)
    if not user_msg or not asst_msg:
        return
    try:
        title = api.generate_title(user_msg["content"], asst_msg["content"])
        title = title[:60]
        api.update_conversation(cid, title=title)
        st.session_state.current_title = title
        st.session_state["title_input"] = title      # 同步顶栏标题输入框
        st.toast(f"✅ 已自动整理标题：{title}", icon="✅")
        st.session_state["_show_title_retry"] = False
    except Exception as e:
        # 不再静默：toast 告知用户 + 标记重试按钮可见
        print(f"[auto-name] failed for cid={cid}: {e}")
        st.toast(f"⚠️ 自动整理标题失败：{e}", icon="⚠️")
        st.session_state["_show_title_retry"] = True
        st.session_state["_title_retry_cid"] = cid


def retry_auto_name():
    """用户主动点「💡 再试一次自动整理」——复用 ai_retitle 路径，但只对当前会话。"""
    cid = st.session_state.get("_title_retry_cid") or st.session_state.current_cid
    if cid:
        ai_retitle(cid)


def ai_retitle(cid: str):
    """手动触发 AI 重新整理标题；对任意会话（含非当前会话）有效。
    当前会话用内存 messages；非当前会话走 api.get_conversation() 拉一次。
    不再用占位符兜底：失败时直接 toast 报错，让用户决定是否重试。"""
    if cid == st.session_state.current_cid:
        msgs = st.session_state.messages
    else:
        try:
            _conv, msgs = api.get_conversation(cid)
        except Exception as e:
            print(f"[ai-retitle] load failed cid={cid}: {e}")
            st.toast(f"⚠️ 加载会话消息失败：{e}", icon="⚠️")
            return
    user_msg = next((m for m in msgs if m["role"] == "user"), None)
    asst_msg = next((m for m in msgs if m["role"] == "assistant"), None)
    if not user_msg or not asst_msg:
        st.toast("需要至少一轮对话才能整理标题", icon="ℹ️")
        return
    try:
        title = api.generate_title(user_msg["content"], asst_msg["content"])
        title = title[:60]
        apply_rename(cid, title, show_toast=False)
        st.toast(f"✅ 已整理标题：{title}", icon="✅")
        if cid == st.session_state.current_cid:
            st.session_state["_show_title_retry"] = False
    except Exception as e:
        print(f"[ai-retitle] generate failed cid={cid}: {e}")
        st.toast(f"⚠️ AI 整理标题失败：{e}", icon="⚠️")
        if cid == st.session_state.current_cid:
            st.session_state["_show_title_retry"] = True
            st.session_state["_title_retry_cid"] = cid


def apply_rename(cid: str, new_title: str, *, show_toast: bool = False) -> bool:
    """把 new_title 清洗后写入 DB，并同步顶栏标题输入框（若是当前活动会话）。
    被 rename_dialog / inline ✎ / ai_retitle 三处共用，避免逻辑漂移。
    返回 True 表示真的改了（写库成功），False 表示清洗后等价于旧值。
    """
    clean = (new_title or "").strip()[:60]
    # 空字符串 / 与旧值等价时不写库；保留原标题
    if not clean:
        return False
    try:
        old = api.get_conversation(cid)[0].get("title", "")
    except Exception:
        old = ""
    if clean == (old or "").strip()[:60]:
        # 即便无变化，也同步一下内存（避免顶栏显示落后于真实状态）
        if st.session_state.current_cid == cid:
            st.session_state.current_title = old or clean
            st.session_state["title_input"] = old or clean
        return False
    api.update_conversation(cid, title=clean)
    if st.session_state.current_cid == cid:
        st.session_state.current_title = clean
        st.session_state["title_input"] = clean
    if show_toast:
        st.toast(f"✅ 已重命名为：{clean}", icon="✅")
    return True


def start_streaming(query: str, regenerate: bool = False, file_metas: list = None):
    cid = st.session_state.current_cid
    if not cid:
        return
    file_ids = []
    user_attachments = []
    if not regenerate:
        file_metas = file_metas or []
        user_attachments = [
            {"file_id": a["id"], "filename": a["filename"],
             "kind": a.get("kind", ""), "chars": a.get("chars", 0)}
            for a in file_metas
        ]
        file_ids = [a["id"] for a in file_metas]
        # 乐观加入用户消息（真实 id 由 iframe start 事件回填）
        st.session_state.messages.append(
            {"id": None, "role": "user", "content": query, "tokens": 0, "model": "",
             "attachments": user_attachments}
        )
    # 图片任务用专用画图模型名落库/展示，否则用会话文本模型
    stream_model = _model_id_for_task(
        st.session_state.current_task, st.session_state.current_model)
    st.session_state.stream_model = stream_model
    st.session_state.stream_query = query
    st.session_state.stream_file_ids = file_ids
    st.session_state.stream_user_attachments = user_attachments
    if USE_IFRAME_STREAM:
        # iframe 模式：不再起后台 SSE 线程、不再累积 buffer，iframe 直接 fetch /chat
        # 用 stream_id 防止 location.reload 后 iframe 重复流式
        import uuid as _uuid
        st.session_state.stream_id = _uuid.uuid4().hex[:12]
        st.session_state.streaming = True
        # iframe 内部已自行处理 stop（sseAbort.abort + 调用 onStreamComplete 保存已产出内容）；
        # 父页面只接收 cp-stream-error 通知到 console，不需主动干预。
        st.rerun()
        return
    # 旧模式（fragment + queue）
    q, stop = api.stream_chat_threaded(
        cid, query, regenerate=regenerate,
        temperature=prefs.get("temperature"), top_p=prefs.get("top_p"),
        max_tokens=prefs.get("max_tokens"),
        file_ids=file_ids,
    )
    st.session_state.stream_queue = q
    st.session_state.stop_event = stop
    st.session_state.stream_buffer = ""
    st.session_state.stream_usage = None
    st.session_state.stream_error = None
    st.session_state.stream_attachments = []
    st.session_state.stream_tool_steps = []
    st.session_state.streaming = True
    st.rerun()


def finalize_streaming():
    """流式结束（完成/停止/出错）后：保存助手消息、更新本地、自动命名。
    iframe 模式：助手消息已由 iframe 自己 POST /messages 落库，这里只清理状态。
    旧模式：继续用累积的 buffer 落库。
    """
    cid = st.session_state.current_cid
    # 新消息会让上次缓存的导出失效
    if cid and st.session_state.get("_export_cache"):
        st.session_state["_export_cache"].pop(cid, None)
        st.session_state["_export_popover_reload"] = True
    if USE_IFRAME_STREAM:
        # iframe 已落库：直接从后端拉最新消息列表，避免丢内容
        try:
            _conv, msgs = api.get_conversation(cid)
            st.session_state.messages = [
                {"id": m["id"], "role": m["role"], "content": m["content"],
                 "tokens": m.get("tokens", 0), "model": m.get("model", ""),
                 "attachments": _coerce_atts(m.get("attachments"))}
                for m in msgs
            ]
        except Exception as e:
            print(f"[finalize] reload messages failed: {e}")
        st.session_state.streaming = False
        st.session_state.last_usage = st.session_state.get("stream_usage") or None
        st.session_state.stream_query = ""
        st.session_state.stream_file_ids = []
        st.session_state.stream_user_attachments = []
        # 自动命名（iframe 没自动跑这步，这里补上）
        maybe_auto_name()
        return
    # 旧路径
    buf = st.session_state.stream_buffer
    usage = st.session_state.stream_usage or {}
    tokens = usage.get("total_tokens", 0)
    model = st.session_state.stream_model
    atts = st.session_state.stream_attachments or []
    steps = list(st.session_state.stream_tool_steps or [])
    if buf.strip() or atts:
        saved = api.save_message(cid, "assistant", buf, tokens=tokens, model=model,
                                 attachments=atts or None)
        st.session_state.messages.append(
            {"id": saved["id"], "role": "assistant", "content": buf,
             "tokens": tokens, "model": model,
             "attachments": _coerce_atts(atts),
             "tool_steps": steps}
        )
    if st.session_state.stream_error:
        st.session_state["_last_error"] = st.session_state.stream_error
    st.session_state.last_usage = usage
    st.session_state.streaming = False
    st.session_state.stream_queue = None
    st.session_state.stop_event = None
    st.session_state.stream_buffer = ""
    st.session_state.stream_usage = None
    st.session_state.stream_error = None
    st.session_state.stream_attachments = []
    st.session_state.stream_tool_steps = []
    maybe_auto_name()


def handle_regen(assistant_msg_id: str):
    cid = st.session_state.current_cid
    msgs = st.session_state.messages
    idx = next((i for i, m in enumerate(msgs) if m["id"] == assistant_msg_id), None)
    if idx is None or idx == 0:
        return
    user_msg = msgs[idx - 1]
    if user_msg["role"] != "user" or not user_msg["id"]:
        return
    # 后端：保留该 user 消息，删掉其后的助手回复
    api.truncate_messages(cid, user_msg["id"], mode="after")
    # 本地：删掉该助手消息及其后
    st.session_state.messages = msgs[:idx]
    start_streaming("", regenerate=True)


def handle_edit_submit(new_text: str):
    cid = st.session_state.current_cid
    mid = st.session_state.editing_msg_id
    if not mid:
        return
    # 后端：删掉该 user 消息及其后
    api.truncate_messages(cid, mid, mode="from")
    # 本地：删掉该消息及其后
    idx = next((i for i, m in enumerate(st.session_state.messages) if m["id"] == mid), None)
    if idx is not None:
        st.session_state.messages = st.session_state.messages[:idx]
    st.session_state.editing_msg_id = None
    start_streaming(new_text, regenerate=False)


# ================ 流式渲染 fragment（可中断） ================
# 节奏说明：
# - iframe 模式：fragment 只做完成探测，**不**渲染助手气泡（iframe 渲了），
#   节奏放慢到 1.5s 足够（用户明显看到已完成的消息才会切回非 streaming）。
# - 旧模式（thread+queue）：节奏 0.5s 既要 drain 队列也要 re-render 气泡，闪烁不可避免。
@st.fragment(run_every=timedelta(seconds=1.5 if USE_IFRAME_STREAM else 0.5))
def streaming_fragment():
    if not st.session_state.streaming:
        return
    if USE_IFRAME_STREAM:
        # iframe 模式：iframe 自己消费 SSE、自己落库；这里只做”轻量轮询 + 状态切换”
        # 当 iframe 通过 postMessage 发 cp-stream-done 时，我们在 fragment 里检测；
        # 兜底：如果 1.5s 内父页面没收到信号，就主动拉一次会话消息列表看是否已有新助手消息。
        _cid = st.session_state.current_cid
        if not _cid:
            return
        try:
            _conv, _msgs = api.get_conversation(_cid)
            # 找最近一条助手消息；如果它在"用户最后一条 user 消息之后"，说明流式已完成
            last_user_idx = max((i for i, m in enumerate(_msgs) if m["role"] == "user"),
                                default=-1)
            after = _msgs[last_user_idx + 1:] if last_user_idx >= 0 else []
            if after and any(m["role"] == "assistant" for m in after):
                # 检测到新助手消息 → 收尾：清 streaming 状态、刷新 messages 列表
                finalize_streaming()
                st.rerun()
                return
        except Exception:
            pass
        # 仍然 streaming：什么都不渲染（iframe 负责显示）
        return
    # 旧模式
    q = st.session_state.stream_queue
    stop_event = st.session_state.stop_event
    if q is None:
        return
    finalized = False

    # 非阻塞地把队列里的事件抽干
    while True:
        try:
            evt = q.get_nowait()
        except queue.Empty:
            break
        t = evt.get("type")
        if t == "start":
            umid = evt.get("user_message_id")
            msgs = st.session_state.messages
            if umid and msgs and msgs[-1]["role"] == "user" and not msgs[-1]["id"]:
                msgs[-1]["id"] = umid
        elif t == "token":
            st.session_state.stream_buffer += evt.get("content", "")
        elif t == "image":
            for a in (evt.get("attachments") or []):
                st.session_state.stream_attachments.append(a)
        elif t == "tool":
            st.session_state.stream_tool_steps.append({
                "name": evt.get("name", ""),
                "args": evt.get("args") or {},
                "status": evt.get("status", "start"),
                "message": evt.get("message"),
            })
        elif t == "file":
            for a in (evt.get("attachments") or []):
                st.session_state.stream_attachments.append(a)
        elif t == "usage":
            st.session_state.stream_usage = evt
        elif t in ("done", "stopped", "error"):
            if t == "error":
                st.session_state.stream_error = evt.get("message", "生成失败")
            finalized = True
            break

    # 渲染当前进度的助手气泡
    buf = st.session_state.stream_buffer
    with st.chat_message("assistant", avatar="🤖"):
        if st.session_state.stream_tool_steps:
            render_tool_steps(st.session_state.stream_tool_steps)
        if buf.strip():
            # render_content 内部对完整 buf 做 markdown 解析；
            # block C 已经把 USE_IFRAME_STREAM 设为 True，此路径只在旧模式走。
            # 频繁重复解析会让输入框式 widget 抖动，下面包装一层 cache。
            render_content(buf)
        else:
            st.markdown(
                '<div class="cp-thinking" aria-label="正在思考">'
                '<span></span><span></span><span></span></div>',
                unsafe_allow_html=True,
            )
        if st.button("停止", key="stop_stream_btn",
                     help="停止生成并保留已产出的内容"):
            stop_event.set()

    if finalized:
        finalize_streaming()
        st.rerun()


# ================ 设置面板 ================
def _on_avatar_change():
    """头像上传回调：仅在选择新文件时触发一次，避免"上传->rerun->再上传"死循环。"""
    up = st.session_state.get("avatar_uploader")
    if up is None:
        return
    try:
        api.upload_avatar(up.getvalue(), up.name)
        st.session_state.prefs = api.get_prefs()
        st.session_state["_avatar_msg"] = "✅ 头像已更新"
    except Exception as e:
        st.session_state["_avatar_msg"] = f"❌ 上传失败：{e}"


def _apply_preset(temp: float, top_p: float, max_tok: int):
    """采样参数预设：写入 session_state 后由 Streamlit 自动 rerun，滑块即刷新。"""
    st.session_state.set_temperature = temp
    st.session_state.set_top_p = top_p
    st.session_state.set_max_tokens = max_tok


def render_personal():
    """个人信息：昵称、头像、主题（侧边栏底部固定区之一）。"""
    with st.expander("👤 个人信息"):
        st.text_input("昵称", value=prefs.get("nickname", "我"), key="set_nickname")

        cur_avatar = prefs.get("avatar_path", "")
        # 头像预览：已上传就显示图片，否则提示默认 emoji
        pcols = st.columns([1, 3])
        if cur_avatar:
            try:
                pcols[0].image(api.avatar_url(cur_avatar), width=64)
            except Exception:
                pcols[0].markdown("🦞")
            pcols[1].caption("当前头像：已上传")
        else:
            pcols[0].markdown("## 🦞")
            pcols[1].caption("当前头像：默认 emoji")
        # 用 on_change 回调上传，不会触发死循环
        st.file_uploader("上传头像（png/jpg/gif/webp）",
                         type=["png", "jpg", "jpeg", "gif", "webp"],
                         key="avatar_uploader", on_change=_on_avatar_change)
        if st.session_state.get("_avatar_msg"):
            st.caption(st.session_state["_avatar_msg"])

        st.selectbox("UI 风格", theme_keys(),
                     format_func=theme_name,
                     index=theme_keys().index(prefs.get("theme") or DEFAULT_THEME),
                     key="set_theme",
                     help="切换界面配色，立即生效；保存后会被记住。")

        # 隐式用户画像：极简 caption，让用户知道系统在"自动适配"，但不打扰
        # 第一次默认值也是 caption 默认值，无需任何初始化代码
        _intent = prefs.get("user_intent") or "general"
        _detail = prefs.get("detail_level") or "normal"
        _intent_label = {"research": "研究", "learn": "学习", "creative": "创意",
                         "general": "通用"}.get(_intent, "通用")
        _detail_label = {"brief": "简洁", "normal": "适中", "deep": "详细"}.get(_detail, "适中")
        pc = st.columns([5, 1])
        pc[0].caption(f"🧠 自动适配模式：{_intent_label} · {_detail_label}")
        if pc[1].button("🧹", key="reset_profile", help="重置自动模式到默认"):
            try:
                st.session_state.prefs = api.reset_profile()
                st.toast("已重置自动模式", icon="🧹")
                st.rerun()
            except Exception as e:
                st.toast(f"重置失败：{e}", icon="⚠️")

        if st.button("💾 保存个人信息", use_container_width=True, key="save_personal_btn"):
            with st.spinner("保存中…"):
                try:
                    api.update_prefs({
                        "nickname": st.session_state.set_nickname,
                        "theme": st.session_state.set_theme,
                    })
                    st.session_state.prefs = api.get_prefs()
                    st.toast("✅ 已保存", icon="✅")
                except Exception as e:
                    st.toast(f"❌ 保存失败：{e}", icon="⚠️")


def render_params():
    """参数设置：采样参数 + 上下文压缩（侧边栏底部固定区之二）。
    采样/压缩参数均带 hover 大白话解释（help），并提供「创意/平衡/精确」预设。"""
    with st.expander("🎛 参数设置"):
        st.caption("💡 不懂这些术语？把鼠标移到参数名旁的 ❓ 上看大白话说明，或直接选一个预设。")
        pc = st.columns(3)
        pc[0].button("🎨 创意", key="preset_creative", use_container_width=True,
                     help="温度 0.9：发散、有想象力，适合写作/头脑风暴",
                     on_click=_apply_preset, args=(0.9, 0.95, 2048))
        pc[1].button("⚖️ 平衡", key="preset_balanced", use_container_width=True,
                     help="温度 0.5：默认稳妥，通用场景",
                     on_click=_apply_preset, args=(0.5, 0.80, 1024))
        pc[2].button("🎯 精确", key="preset_precise", use_container_width=True,
                     help="温度 0.2：稳定、聚焦，适合事实/代码",
                     on_click=_apply_preset, args=(0.2, 0.60, 1024))

        st.slider("温度 temperature", 0.0, 1.0, float(prefs.get("temperature", 0.5)),
                  0.05, key="set_temperature",
                  help="控制回答的随机性与创意度。值越高越发散、有想象力（适合写故事、头脑风暴）；"
                       "越低越稳定、聚焦（适合答事实、写代码）。一般 0.3–0.7。")
        _t = float(st.session_state.get("set_temperature", prefs.get("temperature", 0.5)))
        if _t < 0.4:
            _desc = "🎯 当前风格：偏精确 · 稳定聚焦"
        elif _t < 0.7:
            _desc = "⚖️ 当前风格：平衡 · 通用场景"
        else:
            _desc = "🎨 当前风格：偏发散 · 富有创意"
        st.caption(_desc)

        st.slider("采样概率 top_p", 0.0, 1.0, float(prefs.get("top_p", 0.5)),
                  0.05, key="set_top_p",
                  help="核采样：只从概率累加不超过该值的候选词里挑选。和温度作用类似，"
                       "通常二选一调整即可。1.0 = 不限制。")
        st.slider("最大词源数 max_tokens", 64, 4096,
                  int(prefs.get("max_tokens", 1024)), 64, key="set_max_tokens",
                  help="回复最多生成多少 token（1 个汉字 ≈ 1.5 token）。设太小会被截断，"
                       "设太大更费额度、更慢。")

        st.markdown("##### 🧠 上下文压缩")
        st.slider("保留最近 N 轮原文", 1, 12,
                  int(prefs.get("history_keep", 4)), 1, key="set_history_keep",
                  help="上下文超长时把更早的对话压成摘要，但始终保留最近这几轮完整原文，"
                       "保证近期语境不丢。")
        st.slider("压缩触发阈值（估算 token）", 800, 8000,
                  int(prefs.get("compress_threshold", 3000)), 100, key="set_compress_threshold",
                  help="当本轮对话估算 token 超过该值时触发压缩。越大越晚压缩（更完整但更费额度），"
                       "越小越早压缩。")

        if st.button("💾 保存参数", use_container_width=True, key="save_params_btn"):
            with st.spinner("保存中…"):
                try:
                    api.update_prefs({
                        "temperature": st.session_state.set_temperature,
                        "top_p": st.session_state.set_top_p,
                        "max_tokens": st.session_state.set_max_tokens,
                        "history_keep": st.session_state.set_history_keep,
                        "compress_threshold": st.session_state.set_compress_threshold,
                    })
                    st.session_state.prefs = api.get_prefs()
                    st.toast("✅ 参数已保存", icon="✅")
                except Exception as e:
                    st.toast(f"❌ 保存失败：{e}", icon="⚠️")


@st.dialog("确认删除会话？")
def delete_confirm_dialog(cid: str, title: str):
    st.write(f"将删除「{title}」，此操作不可撤销。")
    cols = st.columns(2)
    if cols[0].button("删除", type="primary", disabled=bool(st.session_state.pop("_delete_locked", False))):
        # 加锁防双击：第一次按下后 rerun 立即吃掉锁，第二次按就 disabled
        st.session_state["_delete_locked"] = True
        try:
            data = api.delete_conversation(cid)
        except Exception as e:
            st.error(f"删除失败：{e}")
            st.session_state["_delete_locked"] = False
            return
        # 后端可能因网络/服务问题返 code != 200
        if isinstance(data, dict) and data.get("code") not in (200, None):
            st.error(f"删除失败：{data.get('message') or data}")
            st.session_state["_delete_locked"] = False
            return
        if st.session_state.current_cid == cid:
            st.session_state.current_cid = None
            st.session_state.messages = []
            st.session_state.current_title = ""
        st.rerun()
    if cols[1].button("取消"):
        st.rerun()


@st.dialog("重命名会话")
def rename_dialog(cid: str, title: str):
    """侧边栏 ⋮ → ✎ 重命名 调起的弹窗；对任意会话（含非当前）有效。
    文本留空时回退为旧标题（通过 apply_rename 内置的等价检查），保证不入空字符串。
    取消时清掉输入缓存，避免重复打开残留上次输入。"""
    st.write("为该会话设置一个新名称：")
    new_title = st.text_input(
        "会话名称",
        value=title,
        max_chars=60,
        key=f"rename_input_{cid}",
        label_visibility="collapsed",
    )
    cols = st.columns(2)
    if cols[0].button("确认", type="primary", key=f"rename_ok_{cid}"):
        apply_rename(cid, new_title or title, show_toast=True)
        # 写完后清掉缓存（避免下次 dialog 打开时还是上次的输入）
        st.session_state.pop(f"rename_input_{cid}", None)
        st.rerun()
    if cols[1].button("取消", key=f"rename_cancel_{cid}"):
        # 清掉 text_input 缓存是关键：Streamlit widget state 按 key 持久跨 rerun
        st.session_state.pop(f"rename_input_{cid}", None)
        st.rerun()


# ================ 侧边栏 ================
@st.fragment
def sidebar_conv_list():
    """历史会话列表 fragment：操作（置顶/重命名/AI整理/删除）只重渲本片段，
    不打断 chat 区正在进行的 SSE 流式输出。每行单行布局：meta + 标题按钮 + ⋮。
    重命名走 ⋮ 弹窗（rename_dialog），避免 inline 编辑破坏单行 grid。"""
    search = st.text_input("🔍 搜索会话", value="", key="conv_search")
    convs = api.list_conversations(search if search.strip() else None)
    st.subheader(f"历史会话（{len(convs)}）")
    if not convs:
        # 空状态：有/无搜索关键词不同
        if search.strip():
            st.caption(f"🔍 没找到包含「{search.strip()}」的会话")
            if st.button("清除搜索", key="clear_conv_search", use_container_width=True):
                st.session_state["conv_search"] = ""
                st.rerun()
        else:
            st.markdown(
                "<div style='padding:16px 8px;color:#9ca3af;font-size:13px;"
                "border:1px dashed #e5e7eb;border-radius:8px;text-align:center;'>"
                "💬 还没有对话<br>在下方输入第一条消息开始吧"
                "</div>",
                unsafe_allow_html=True,
            )
        return
    for c in convs:
        _render_one_conv_row(c)


def _render_one_conv_row(c: dict):
    """单条历史会话行：meta + 标题按钮 + ⋮ 菜单（单行 CSS grid 布局）。"""
    cid = c["id"]
    prefix = "📌 " if c["pinned"] else ""
    active = c["id"] == st.session_state.current_cid
    with st.container(key=f"cp_row_{cid}"):
        # 1) 左：emoji + 相对时间（CSS grid 的 auto 列）
        st.markdown(
            f"<div class='cp-conv-meta'>"
            f"<span class='cp-conv-emoji'>{_task_icon(c.get('task', ''))}</span>"
            f"<span class='cp-conv-time'>· {_rel_time(c.get('updated_at', ''))}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        # 2) 中：标题按钮（1fr 列，长时自动 ellipsis；📌 表示钉住）
        if st.button(f"{prefix}{c['title']}", key=f"cv_{cid}",
                     type="primary" if active else "secondary"):
            switch_conversation(cid)
            st.rerun()
        # 3) 右：⋮ 菜单 - 置顶 / ✎ 重命名 / 💡 AI 整理 / 🗑 删除
        with st.popover("⋮", key=f"menu_{cid}", help="更多操作"):
            pin_label = "取消置顶" if c["pinned"] else "置顶"
            if st.button(pin_label, key=f"pin_{cid}"):
                api.update_conversation(cid, pinned=0 if c["pinned"] else 1)
                st.rerun()
            if st.button("✎ 重命名", key=f"ren_{cid}"):
                rename_dialog(cid, c["title"])
            # AI 整理标题对任意会话开放：用户可能想换个更合适的标题
            if st.button("💡 AI 整理标题", key=f"ai_{cid}"):
                ai_retitle(cid)
                st.rerun()
            if st.button("🗑 删除", key=f"del_{cid}"):
                delete_confirm_dialog(cid, c["title"])

with st.sidebar:
    st.title("🤖 chatbot-plus")

    st.subheader("✨ 新建对话")
    task_options = {t["key"]: f"{t['icon']} {t['name']}" for t in st.session_state.tasks}
    st.selectbox("任务类型", list(task_options.keys()),
                 format_func=lambda k: task_options.get(k, k),
                 key="new_task")
    _nt = next((t for t in st.session_state.tasks if t["key"] == st.session_state.new_task), None)
    _nt_is_image = bool(_nt and _nt.get("model") in ("image_gen", "image_edit"))
    # 当前新建任务实际使用的模型（图片任务=专用画图模型，否则=选中的文本模型）
    _eff_model = _model_id_for_task(st.session_state.new_task,
                                    st.session_state.new_model or st.session_state.default_model)
    _eff_meta_map = st.session_state.image_meta if _nt_is_image else st.session_state.model_meta
    _eff_meta = (_eff_meta_map or {}).get(_eff_model, {})
    # 文本模型下拉：悬停(help)显示该模型详细描述；图片任务禁用（不生效）
    _help = None if _nt_is_image else (_eff_meta.get("desc") or f"当前选中的文本模型：{_eff_model}")
    st.selectbox("模型", st.session_state.models, key="new_model",
                 help=_help, disabled=_nt_is_image)
    if _nt_is_image:
        st.caption("⚙️ 该任务使用专用画图模型，下方文本模型选项不生效。")
    # 模型简介：上下文/多模态/特色/价格（图片任务展示画图模型信息）
    _render_model_info(_eff_model, _eff_meta_map)
    if st.button("➕ 新建对话", use_container_width=True):
        new_conversation()

    st.divider()

    # 会话列表：抽到 fragment（操作只重渲本片段，不打断 SSE 流）
    sidebar_conv_list()

    # 底部固定区：个人信息 + 参数设置（CSS 据锚点 .cp-bottom-anchor 钉在侧边栏底部）
    with st.container():
        st.markdown('<div class="cp-bottom-anchor"></div>', unsafe_allow_html=True)
        render_personal()
        render_params()


# ================ 主区域 ================
if st.session_state.get("_attach_err"):
    st.error(f"📎 {st.session_state['_attach_err']}")
    del st.session_state["_attach_err"]

if st.session_state.get("_last_error"):
    st.error(f"⚠️ {st.session_state['_last_error']}")
    del st.session_state["_last_error"]

# 部分加载成功提示（load_meta 并发改进后：prefs 成功但 tasks 或 models 失败时）
_warn = st.session_state.pop("_partial_meta_warn", None)
if _warn:
    st.warning(f"⚠️ 部分元数据未加载（仍可继续使用）：{_warn}")

if st.session_state.current_cid:
    # 顶栏包进 container + 锚点：CSS 据 .cp-topbar-anchor 把本容器钉为主区顶部
    # 半透明材质粘性条（wayfinding：始终显示当前会话标题/任务/导出）。
    with st.container():
        st.markdown('<div class="cp-topbar-anchor"></div>', unsafe_allow_html=True)
        header = st.columns([7, 2, 1])
        # 切换会话时重置标题输入框
        if st.session_state.get("_title_cid") != st.session_state.current_cid:
            st.session_state["_title_cid"] = st.session_state.current_cid
            st.session_state["title_input"] = st.session_state.current_title

        def on_title_change():
            new_t = st.session_state.title_input.strip() or "新对话"
            api.update_conversation(st.session_state.current_cid, title=new_t)
            st.session_state.current_title = new_t
            # 用户主动改名为非占位 → 关闭"再试一次"提示
            if new_t and new_t != "新对话":
                st.session_state["_show_title_retry"] = False

        header[0].text_input("标题", label_visibility="collapsed",
                             key="title_input", on_change=on_title_change)
        # 自动整理失败时：紧贴顶栏下方显示「💡 再试一次」按钮（不打扰主流程）
        if st.session_state.get("_show_title_retry"):
            rc = st.columns([4, 1, 3])
            rc[1].button("💡 再试一次自动整理", key="retry_auto_name",
                         help="上一次自动整理标题失败，点击重试",
                         on_click=retry_auto_name)
        header[1].markdown(f"`{task_name(st.session_state.current_task)}`")

        with header[2].popover("⬇️", use_container_width=True, help="导出当前会话"):
            st.caption("导出当前会话")
            # 懒导出：只有用户点展开时才拉后端；同一个 cid 在 session 期内只拉一次。
            _cid_now = st.session_state.current_cid
            _export_cache = st.session_state.setdefault(
                "_export_cache", {})      # {cid: {"md": ..., "json": ...}}
            if st.session_state.get("_export_popover_reload"):
                st.session_state["_export_popover_reload"] = False
                _export_cache.pop(_cid_now, None)
            _exp = _export_cache.get(_cid_now)
            if _exp is None:
                try:
                    md = api.export_conversation(_cid_now, "md")
                    js = api.export_conversation(_cid_now, "json")
                    _exp = {"md": md, "json": js}
                    _export_cache[_cid_now] = _exp
                except Exception as e:
                    st.caption(f"导出失败：{e}")
                    _exp = None
            if _exp:
                st.download_button("Markdown", data=_exp["md"]["content"],
                                   file_name=_exp["md"]["filename"],
                                   mime="text/markdown",
                                   use_container_width=True)
                st.download_button("JSON", data=_exp["json"]["content"],
                                   file_name=f"{st.session_state.current_title}.json",
                                   mime="application/json",
                                   use_container_width=True)
            else:
                st.button("🔄 重试导出", key="_export_retry",
                          use_container_width=True,
                          on_click=lambda: st.session_state.update(
                              {"_export_popover_reload": True}))
else:
    # 图片任务不显示通用欢迎语与灵感话题（改由下方提示词模版引导）
    if not _is_image_task():
        _nick = html.escape(prefs.get("nickname") or "我")
        st.markdown(
            f"<div class='cp-hero'>"
            f"<div class='cp-hero-logo'>🤖</div>"
            f"<h2>你好，{_nick} 👋</h2>"
            f"<p>有什么可以帮你的？在下方输入消息，或挑一个灵感话题直接开始。</p>"
            f"</div>",
            unsafe_allow_html=True,
        )
        # 空会话：展示几个随机灵感问题，点击即发送
        if (not st.session_state.streaming
                and not st.session_state.editing_msg_id
                and not st.session_state.messages):
            sugg = st.session_state.suggestions or pick_suggestions()
            st.session_state.suggestions = sugg
            cols = st.columns(2)
            for i, s in enumerate(sugg):
                if cols[i % 2].button(s, key=f"sg_{i}", use_container_width=True,
                                       type="secondary"):
                    send_suggestion(s)
            # 灵感卡片样式由注入脚本据 sugg 列表自动打类（见底部 components.html）

# 图片生成/编辑任务：空会话时展示提示词模版卡片，点击即发送
if (not st.session_state.streaming
        and not st.session_state.editing_msg_id
        and _is_image_task()
        and not st.session_state.messages):
    t = _current_task_obj() or {}
    st.markdown(f"#### {t.get('icon','🎨')} {t.get('name','图片生成')} 提示词模版")
    if t.get("key") == "image_edit":
        st.caption("📎 先在输入框上传一张原图，再点下方模版或自行描述修改要求。")
    else:
        st.caption("💡 点模版直接生成，也可在输入框自行描述（主体+环境+光线+风格）。")
    st.caption("⚙️ 此任务自动使用专用画图模型，与会话所选文本模型无关。")
    tpls = t.get("templates") or []
    cols = st.columns(2)
    for i, tp in enumerate(tpls):
        if cols[i % 2].button(f"{tp['title']}", key=f"tpl_{i}",
                              use_container_width=True, type="secondary",
                              help=tp["prompt"]):
            send_template(tp["prompt"])
    # 模版卡片复用灵感卡片样式：把标题喂给注入脚本打类
    _tpl_titles = [tp["title"] for tp in tpls]
    st.session_state["_tpl_titles"] = _tpl_titles

# 渲染历史消息
user_avatar_path = prefs.get("avatar_path", "")
for m in st.session_state.messages:
    if m["role"] == "user":
        # 用户：自定义 HTML 气泡，靠右（微信式）
        st.markdown(
            user_bubble_html(m["content"], user_avatar_path,
                             m.get("attachments")),
            unsafe_allow_html=True,
        )
        if not st.session_state.streaming:
            # 编辑按钮：小图标，靠右对齐
            uc = st.columns([10, 1])
            if uc[1].button("✏️", key=f"ed_{m['id']}",
                            help="编辑后重发"):
                st.session_state.editing_msg_id = m["id"]
                st.session_state["edit_text"] = m["content"]
                st.rerun()
    else:
        # 助手：st.chat_message 靠左，保留代码块复制
        with st.chat_message("assistant", avatar="🤖"):
            # 重新加载的消息也可能含 tool_steps（仅本会话有效）
            if m.get("tool_steps"):
                render_tool_steps(m["tool_steps"])
            render_content(m["content"])
            # 助手消息附件（图片生成/编辑结果等）：图片缩略图可点击看大图
            _atts_html = attachments_html(m.get("attachments"))
            if _atts_html:
                st.markdown(_atts_html, unsafe_allow_html=True)
            _img_n = sum(1 for a in (m.get("attachments") or [])
                         if a.get("kind") == "image")
            # 图片生成/编辑消息：以会话任务对应的专用画图模型为准展示，
            # 不信任落库的 model——早期版本曾把文本模型名误存到图片消息上，
            # 这里按任务实时推导，修正历史脏数据（实际用的就是画图模型）。
            if _img_n and _is_image_task():
                shown_model = _model_id_for_task(st.session_state.current_task, "")
            else:
                shown_model = m.get("model", "")
            info = []
            if shown_model:
                info.append(shown_model)
            if _img_n:
                info.append(f"🖼️ {_img_n} 张图")
            elif m.get("tokens"):
                info.append(f"{m['tokens']} tokens")
            if info:
                st.markdown(
                    "<div class='cp-meta'>"
                    + " · ".join(html.escape(i) for i in info)
                    + "</div>",
                    unsafe_allow_html=True,
                )
            if not st.session_state.streaming:
                # 操作栏：重新生成（小图标）
                _act = st.columns([1, 7])
                if _act[0].button("🔄", key=f"rg_{m['id']}", help="重新生成回复"):
                    handle_regen(m["id"])
                # 复制全文：展开后用 st.code 的原生复制按钮（主文档 realm，macOS 可靠）。
                # 旧的 iframe 注入式复制在 Safari 跨 realm 被阻断，已弃用。
                with st.expander("📋 复制全文", expanded=False):
                    st.code(m["content"], language="markdown")

# 编辑框
if st.session_state.editing_msg_id and not st.session_state.streaming:
    with st.container(border=True):
        # 锚点：CSS 据 .cp-edit-anchor 给本容器加入场过渡（teleporting state -> 动画桥接）
        st.markdown('<div class="cp-edit-anchor"></div>', unsafe_allow_html=True)
        st.caption("✏️ 编辑消息后重发（会截断其后所有内容）")
        st.text_area("编辑内容", key="edit_text", height=100)
        ec = st.columns([1, 1, 4])
        if ec[0].button("重发", type="primary"):
            txt = st.session_state.edit_text.strip()
            if txt:
                handle_edit_submit(txt)
        if ec[1].button("取消"):
            st.session_state.editing_msg_id = None
            st.rerun()

# 流式渲染：USE_IFRAME_STREAM 时挂一个 iframe（marked.js + 0 rerun + 无闪烁）
if st.session_state.streaming:
    if USE_IFRAME_STREAM:
        # iframe 模式：组件直接 POST /chat 并自己解析 SSE，0 Streamlit rerun
        # 父页面只需把当前会话/查询/附件/模型传给 iframe；iframe 完成后通过
        # postMessage cp-stream-done + 后端新消息轮询让父页面切回正常渲染。
        _iframe_params = {
            "cid": st.session_state.current_cid,
            "query": st.session_state.get("stream_query") or "",
            "regenerate": False,
            "file_ids": st.session_state.get("stream_file_ids") or [],
            "user_attachments": st.session_state.get("stream_user_attachments") or [],
            "model": st.session_state.get("stream_model") or "",
            "temperature": prefs.get("temperature"),
            "top_p": prefs.get("top_p"),
            "max_tokens": prefs.get("max_tokens"),
            "backend_url": api.BASE_URL,
            "stream_id": st.session_state.get("stream_id") or "default",
        }
        components.html(render_stream_iframe(height=560, params=_iframe_params),
                        height=560, scrolling=True)
    # iframe 与旧模式都跑 fragment：iframe 模式它只做"轮询后端检测新消息 → finalize"，
    # 旧模式它做完整的事件消费与渲染。
    streaming_fragment()

# 最近一次 token 用量
if st.session_state.get("last_usage"):
    u = st.session_state.last_usage
    if u.get("image_task"):
        # 图片任务不产生文本 token，显示画图模型 + 不计 token 提示，而非误导性的 0
        _pills = [
            "<span class='cp-pill cp-pill-accent'>🎨 画图任务 · 不计文本 token</span>",
            f"<span class='cp-pill'>{html.escape(st.session_state.stream_model or '')}</span>",
        ]
    else:
        _pills = [
            f"<span class='cp-pill'>⌨️ 输入 {u.get('prompt_tokens', 0)}</span>",
            f"<span class='cp-pill'>✍️ 输出 {u.get('completion_tokens', 0)}</span>",
            f"<span class='cp-pill cp-pill-accent'>合计 {u.get('total_tokens', 0)} tokens</span>",
        ]
        if u.get("compressed"):
            _pills.append("<span class='cp-pill cp-pill-warn'>🗜 已压缩</span>")
    st.markdown(f"<div class='cp-usage'>{''.join(_pills)}</div>",
                unsafe_allow_html=True)

# ---------------- 附件 + 聊天输入 ----------------
# 用 st.chat_input 原生 accept_file：文件按钮由 Streamlit 自动放在输入框最左侧，
# 定位正确、不会与输入框粘连，且自带文件名 chip 与移除按钮。提交时一并拿到 text + files。
chat_disabled = st.session_state.streaming or bool(st.session_state.editing_msg_id)
_ATTACH_TYPES = ["txt", "md", "markdown", "py", "js", "ts", "java", "c", "cpp", "go",
                 "rs", "rb", "php", "sh", "sql", "json", "yaml", "yml", "xml", "html",
                 "css", "csv", "tsv", "toml", "log", "ini", "cfg", "conf", "r", "lua",
                 "png", "jpg", "jpeg", "gif", "webp"]

# 注入主文档脚本：灵感卡片样式 + 流式 iframe 错误监听。
# 必须用 components.html（iframe 带 allow-scripts + allow-same-origin），st.html 会被 DOMPurify 清掉 <script>。
# 卡片样式同时作用于灵感问题与图片任务提示词模版（按按钮文本匹配）。
# Hash 缓存：当 sugg / tpl 列表本轮与上轮一致时跳过 components.html 注入（避免每 rerun 加 iframe）。
_sugg_for_cards = list(st.session_state.suggestions or [])
_sugg_for_cards += list(st.session_state.get("_tpl_titles") or [])
_sugg_hash_now = hash(tuple(_sugg_for_cards))
if st.session_state.get("_sugg_injected_hash") != _sugg_hash_now:
    components.html(_cp_components_js(_sugg_for_cards), height=0)
    st.session_state["_sugg_injected_hash"] = _sugg_hash_now

# 聊天输入占位符随任务调整：图片编辑提示上传原图
_cto = _current_task_obj()
_base_ph = ("描述修改要求（需先上传原图）…"
            if (_cto and _cto.get("key") == "image_edit")
            else "输入消息开始聊天…")

# 工具 chips（豆包风格：紧贴输入框上方一行水平 chip）--
# 点击 = 选中/取消选中（不发送！）。选中后 chip 高亮，输入框 placeholder 切换为该工具的
# 示例提示，引导用户输入自己的具体内容；发送时保持用户输入原文，后端 agent 自动选用工具。
# 仅文本任务显示（图片任务已有自己的提示词模版卡片）。
_TOOL_PLACEHOLDERS = {
    "info":   "已选「实时信息」· 输入如：北京今天天气、100 美元换多少人民币…",
    "github": "已选「GitHub 搜索」· 输入要找的开源库关键词…",
    "local":  "已选「数学计算」· 输入算式如：(3.14*12**2)/2 …",
    "image":  "已选「图片生成」· 输入画面描述（主体+环境+光线+风格）…",
    "doc":    "已选「文档生成」· 输入主题与要求，如：5 页关于 AI 的 PPT…",
}


@st.fragment
def chips_panel_5():
    """工具栏 5 chip。永远渲染；缺元数据 → 单 chip 标灰 disabled，不让整列消失。

    设计：
    - 5 个固定 chip 按 CHIP_LAYOUT 顺序渲染（不依赖后端返回顺序 → 视觉稳定）。
    - /tools 元数据走 session_state 缓存（默认 30s 内不重拉）：点 chip 不再同步等网络。
    - 图片任务下：上行加 caption、5 chip 全 disabled（不消失）。
    - 选中态用 session_state['_selected_tool'] 标记；切回 None = 取消。
    """
    from components.toolbar import CHIP_LAYOUT
    import time as _t

    # ---- /tools 元数据缓存：避免每次点 chip 都同步等网络 ----
    # 点 chip 的 fragment rerun 应该是「瞬时」的，否则用户会以为「没反应 → 再点 → toggle 取消」。
    # 空响应（后端抖一下 / 没拉到）不写时间戳，下次允许立即重试，避免锁 30 秒 + 「提示说已选但没 chip 亮」撕裂。
    _cache_ts = st.session_state.get("_tool_groups_cache_ts") or 0
    if (_t.time() - _cache_ts) > 30:
        try:
            _groups_raw = api.get_tool_groups()
            if isinstance(_groups_raw, list) and _groups_raw:
                st.session_state["_tool_groups_cache"] = _groups_raw
                st.session_state["_tool_groups_cache_ts"] = _t.time()
            elif isinstance(_groups_raw, list) and not _groups_raw:
                # 后端没拉到 → 不写时间戳；同步清掉选中态避免 UI 撕裂
                st.session_state["_tool_groups_cache"] = []
                st.session_state["_tool_groups_cache_ts"] = 0
                if st.session_state.get("_selected_tool"):
                    st.session_state["_selected_tool"] = None
        except Exception:
            # 网络异常：清掉时间戳，下次重试
            st.session_state["_tool_groups_cache_ts"] = 0
    groups_raw = st.session_state.get("_tool_groups_cache") or []
    groups = ({g["key"]: g for g in groups_raw if isinstance(g, dict) and g.get("key")}
              if isinstance(groups_raw, list) else {})

    is_image_task = _is_image_task()
    sel = st.session_state.get("_selected_tool")

    # 容器的 streamlit key = "cp_tool_chips"：与 themes.py .st-key-cp_tool_chips 选择器对接
    with st.container(key="cp_tool_chips"):
        # caption 行：图片任务提示 / 选中工具提示 —— 互斥、占同一行槽位，零额外跳动
        if is_image_task:
            st.markdown(
                "<div class='cp-toolbar-caption'>🎨 图片任务已选定 · "
                "工具栏已禁用，切回文本任务可启用</div>",
                unsafe_allow_html=True,
            )
        elif sel and sel in _TOOL_PLACEHOLDERS:
            st.markdown(
                f"<div class='cp-toolbar-caption'>{html.escape(_TOOL_PLACEHOLDERS[sel])}</div>",
                unsafe_allow_html=True,
            )
        cols = st.columns(len(CHIP_LAYOUT), gap="small")
        for i, (key, label) in enumerate(CHIP_LAYOUT):
            g = groups.get(key)
            ready = bool(g and (g.get("ready") or g.get("tools")))
            disabled = (not ready) or is_image_task
            is_sel = (sel == key) and ready
            help_txt = (g.get("hint") if g and g.get("hint") else None) \
                or "未就绪：后端工具尚未加载"
            if is_image_task:
                help_txt = "图片任务下工具已禁用"
            if cols[i].button(
                label,
                key=f"tool_chip_{key}",
                help=help_txt,
                disabled=disabled,
                type="primary" if is_sel else "secondary",
                use_container_width=True,
            ):
                # 关键：handler 内主动 rerun fragment，让新 state 立刻重绘 5 个 chip。
                # 否则 button 已用旧 sel 渲染完 → 用户看到「点 A 没反应」→ 再点 → toggle 取消。
                cur = st.session_state.get("_selected_tool")
                st.session_state["_selected_tool"] = None if (cur == key) else key
                st.rerun(scope="fragment")


# 永远渲染 5 chip（不再有 `if _tool_groups and not _is_image_task()` 这种会让整列消失的 gate）。
chips_panel_5()
# 注：「已选 X」的引导文案由 chips_panel_5 fragment 自己渲染在 caption 行
# （同 .cp-toolbar-caption 槽位，与图片任务 caption 互斥）。
# 这里不再读 _selected_tool，避免跨 fragment stale 依赖。

# 上次附件上传失败留下的文本：让用户改完附件再「重发」或「仅发文本」
if st.session_state.get("_retry_text"):
    _rc = st.columns([10, 1, 1])
    _rc[0].text_area(
        "📎 上次附件上传失败，可编辑后重发（仍无附件）",
        value=st.session_state["_retry_text"],
        key="_retry_text_input", height=80,
    )
    if _rc[1].button("仅发文本", key="_retry_text_only"):
        _txt = (st.session_state.get("_retry_text_input")
                or st.session_state["_retry_text"]).strip()
        st.session_state["_retry_text"] = None
        st.session_state.pop("_retry_text_input", None)
        if _txt:
            ensure_conversation()
            start_streaming(_txt, regenerate=False)
    if _rc[2].button("放弃", key="_retry_text_drop"):
        st.session_state["_retry_text"] = None
        st.session_state.pop("_retry_text_input", None)
        st.rerun()
    st.divider()

prompt = st.chat_input(_base_ph, accept_file="multiple",
                       file_type=_ATTACH_TYPES, disabled=chat_disabled,
                       key="cp_chat_input")
if prompt and not chat_disabled:
    # accept_file="multiple" 时返回 ChatInputValue（含 .text / .files）
    if isinstance(prompt, str):
        text, files = prompt, []
    else:
        text = prompt.text or ""
        files = prompt.files or []
    text = text.strip()
    # 上传附件（若有）。失败时把 text 暂存到 session_state，让用户在 retry 框里重发——
    # 修复 bug：原本直接 st.rerun() 会让 chat_input 的内容丢光，用户被迫重打整段话。
    file_metas = []
    if files:
        try:
            file_metas = api.upload_files(list(files))
        except Exception as e:
            st.session_state["_attach_err"] = f"附件上传失败：{e}"
            st.session_state["_retry_text"] = text  # 保留用户输入
            st.rerun()
            # 此处不能 return（顶层 script 上下文）；st.rerun() 会重跑整页
    if text or file_metas:
        ensure_conversation()
        start_streaming(text, regenerate=False, file_metas=file_metas)
