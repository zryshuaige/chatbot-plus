'''chatbot-plus 前端：Streamlit 多轮聊天应用。
特性：任务系统提示词、头像、主题、历史自动命名、上下文压缩、
流式可中断、重生成/编辑、多模型+token用量、会话搜索/导出。'''
from datetime import timedelta

import html
import json
import queue
import streamlit as st
import streamlit.components.v1 as components

import api_client as api
from themes import theme_css, theme_keys, theme_name, DEFAULT_THEME
from render import render_content, user_bubble_html, copy_chip_html, _normalize_attachments as _coerce_atts

st.set_page_config(page_title="chatbot-plus", page_icon="🤖", layout="wide",
                   initial_sidebar_state="expanded")


# ================ 注入脚本（经 components.html 在 allow-same-origin 的 iframe 执行，
# 操作 window.parent 即主应用文档）================
# 说明：st.html 会用 DOMPurify 清掉 <script>，JS 根本不执行；st.markdown 会清掉 on* 事件。
# 唯一能在主文档跑 JS 的途径是 components.html（iframe 带 allow-scripts + allow-same-origin）。
# 附件按钮已改用 st.chat_input(accept_file=...) 原生实现（自动位于输入框最左侧），无需 JS 定位。
# 这里只做三件 CSS 搞不定的事：复制全文（事件委托）、流式光标/停止胶囊、灵感卡片打卡片样式。
_SUGG_ICONS = ["💡", "✍️", "🧠", "🚀"]


def _cp_components_js(sugg: list) -> str:
    """返回注入主文档的脚本。sugg=当前灵感问题列表（用于给灵感按钮打卡片样式）。"""
    sugg_json = json.dumps(sugg or [], ensure_ascii=False)
    icons_json = json.dumps(_SUGG_ICONS, ensure_ascii=False)
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

  // ---- 复制助手全文（事件委托，按钮每次 rerun 重建，委托一次即可）----
  function cpCopyFallback(text){{
    var ta = d.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    d.body.appendChild(ta); ta.select();
    try {{ d.execCommand('copy'); }} catch (e) {{}}
    d.body.removeChild(ta);
  }}
  w.cpCopy = function(el){{
    var bin = atob(el.dataset.b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    var text = new TextDecoder('utf-8').decode(bytes);
    var done = function(){{
      el.classList.add('cp-copied');
      var old = el.getAttribute('data-label') || el.innerHTML;
      el.setAttribute('data-label', old);
      el.innerHTML = '✓ 已复制';
      setTimeout(function () {{ el.classList.remove('cp-copied'); el.innerHTML = old; }}, 1400);
    }};
    if (w.navigator.clipboard && w.navigator.clipboard.writeText) {{
      w.navigator.clipboard.writeText(text).then(done, function () {{ cpCopyFallback(text); done(); }});
    }} else {{ cpCopyFallback(text); done(); }}
  }};

  // ---- 流式模式：从 DOM 推断（有 .cp-thinking=思考中；有「停止」按钮=流式中）----
  function applyStreamMode(){{
    var msgs = d.querySelectorAll('[data-testid="stChatMessage"]');
    for (var i = 0; i < msgs.length; i++) {{ msgs[i].classList.remove('cp-streaming', 'cp-thinking-bubble'); }}
    var last = msgs[msgs.length - 1];
    if (!last) return;
    var btns = last.querySelectorAll('button');
    var stopBtn = null;
    for (var j = 0; j < btns.length; j++) {{ if (btns[j].textContent.trim().indexOf('停止') !== -1) {{ stopBtn = btns[j]; break; }} }}
    if (last.querySelector('.cp-thinking')) {{ last.classList.add('cp-thinking-bubble'); }}
    else if (stopBtn) {{ last.classList.add('cp-streaming'); stopBtn.classList.add('cp-stop-btn'); }}
  }}

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

  w.__cpSync = function(){{
    applyStreamMode();
    tagSuggestions(w.__cpSugg || [], w.__cpSuggIcons || []);
  }};

  // ---- 一次性挂载：事件委托 + MutationObserver + 兜底轮询 ----
  if (!w.__cpReady) {{
    w.__cpReady = true;
    d.addEventListener('click', function (e){{
      var el = e.target.closest && e.target.closest('.cp-act[data-b64]');
      if (el) {{ e.preventDefault(); w.cpCopy(el); }}
    }});
    var raf = 0;
    var schedule = function () {{
      if (raf) return;
      raf = w.requestAnimationFrame(function () {{ raf = 0; if (w.__cpSync) w.__cpSync(); }});
    }};
    new w.MutationObserver(schedule).observe(d.body, {{ childList: true, subtree: true }});
    w.addEventListener('resize', schedule);
    setInterval(schedule, 300);
  }}

  // ---- 本轮状态注入（每次 rerun 都执行）----
  w.__cpSugg = {sugg_json};
  w.__cpSuggIcons = {icons_json};
  if (w.__cpSync) w.__cpSync();
}})();
</script>"""


# ================ 会话状态初始化 ================
def init_state():
    defaults = {
        "prefs": None,
        "tasks": [],
        "models": [],
        "default_model": "",
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
        "last_usage": None,        # 最近一次 token 用量（展示）
        "editing_msg_id": None,    # 正在编辑的用户消息 id
        "prefs_loaded": False,
        "new_task": "daily",       # 侧边栏“新建对话”用的任务
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
    "如何回复面试官‘你最大的缺点是什么’？",
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
    """当前任务对象（优先 current_task，新建时回退 new_task）。"""
    key = st.session_state.current_task or st.session_state.new_task
    return next((t for t in st.session_state.tasks if t["key"] == key), None)


def _is_image_task() -> bool:
    t = _current_task_obj()
    return bool(t and t.get("model") in ("image_gen", "image_edit"))


def send_template(text: str):
    """点击提示词模版：创建会话并发送（与 send_suggestion 同路径）。"""
    ensure_conversation()
    start_streaming(text, regenerate=False)


def load_meta():
    """首次加载偏好/任务/模型。"""
    if not st.session_state.prefs_loaded:
        st.session_state.prefs = api.get_prefs()
        st.session_state.tasks = api.get_tasks()
        st.session_state.models, st.session_state.default_model = api.get_models()
        if not st.session_state.new_model:
            st.session_state.new_model = (st.session_state.prefs.get("default_model")
                                          or st.session_state.default_model)
        st.session_state.prefs_loaded = True


load_meta()
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
    # 这样“历史会话”里不会残留没有任何内容的会话。
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
        api.update_conversation(cid, title=title)
        st.session_state.current_title = title
    except Exception:
        pass


def start_streaming(query: str, regenerate: bool = False, file_metas: list = None):
    cid = st.session_state.current_cid
    if not cid:
        return
    file_ids = []
    if not regenerate:
        file_metas = file_metas or []
        attachments_meta = [
            {"file_id": a["id"], "filename": a["filename"],
             "kind": a.get("kind", ""), "chars": a.get("chars", 0)}
            for a in file_metas
        ]
        file_ids = [a["id"] for a in file_metas]
        # 乐观加入用户消息（真实 id 由 start 事件回填）
        st.session_state.messages.append(
            {"id": None, "role": "user", "content": query, "tokens": 0, "model": "",
             "attachments": attachments_meta}
        )
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
    st.session_state.stream_model = st.session_state.current_model
    st.session_state.streaming = True
    st.rerun()


def finalize_streaming():
    """流式结束（完成/停止/出错）后：保存助手消息、更新本地、自动命名。"""
    cid = st.session_state.current_cid
    buf = st.session_state.stream_buffer
    usage = st.session_state.stream_usage or {}
    tokens = usage.get("total_tokens", 0)
    model = st.session_state.stream_model
    atts = st.session_state.stream_attachments or []
    if buf.strip() or atts:
        saved = api.save_message(cid, "assistant", buf, tokens=tokens, model=model,
                                 attachments=atts or None)
        st.session_state.messages.append(
            {"id": saved["id"], "role": "assistant", "content": buf,
             "tokens": tokens, "model": model,
             "attachments": _coerce_atts(atts)}
        )
    st.session_state.last_usage = usage
    st.session_state.streaming = False
    st.session_state.stream_queue = None
    st.session_state.stop_event = None
    st.session_state.stream_buffer = ""
    st.session_state.stream_usage = None
    st.session_state.stream_attachments = []
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
@st.fragment(run_every=timedelta(seconds=0.3))
def streaming_fragment():
    if not st.session_state.streaming:
        return
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
            # 图片生成/编辑：助手消息携带的图片附件，finalize 时随消息落库与展示
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
        if buf.strip():
            render_content(buf)
        else:
            # 首个 token 到达前：三点跳动“思考中”动画
            st.markdown(
                '<div class="cp-thinking" aria-label="正在思考">'
                '<span></span><span></span><span></span></div>',
                unsafe_allow_html=True,
            )
        if st.button("停止", key="stop_stream_btn",
                     help="停止生成并保留已产出的内容"):
            stop_event.set()
    # 流式光标 / 入场动画 / 停止胶囊由注入脚本里的 MutationObserver 据此气泡内容自动打类

    if finalized:
        finalize_streaming()
        st.rerun()


# ================ 设置面板 ================
def _on_avatar_change():
    """头像上传回调：仅在选择新文件时触发一次，避免“上传->rerun->再上传”死循环。"""
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


def render_settings():
    """偏好设置：昵称、头像、主题、采样参数、压缩策略。
    采样/压缩参数均带 hover 大白话解释（help），并提供「创意/平衡/精确」预设。"""
    with st.expander("⚙️ 个性化设置"):
        st.markdown("#### 👤 个人资料")
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

        st.markdown("#### 🎨 外观")
        st.selectbox("UI 风格", theme_keys(),
                     format_func=theme_name,
                     index=theme_keys().index(prefs.get("theme") or DEFAULT_THEME),
                     key="set_theme",
                     help="切换界面配色，立即生效；保存后会被记住。")

        st.markdown("#### 🎛 采样参数")
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

        st.markdown("#### 🧠 上下文压缩")
        st.slider("保留最近 N 轮原文", 1, 12,
                  int(prefs.get("history_keep", 4)), 1, key="set_history_keep",
                  help="上下文超长时把更早的对话压成摘要，但始终保留最近这几轮完整原文，"
                       "保证近期语境不丢。")
        st.slider("压缩触发阈值（估算 token）", 800, 8000,
                  int(prefs.get("compress_threshold", 3000)), 100, key="set_compress_threshold",
                  help="当本轮对话估算 token 超过该值时触发压缩。越大越晚压缩（更完整但更费额度），"
                       "越小越早压缩。")

        if st.button("💾 保存设置", use_container_width=True):
            api.update_prefs({
                "nickname": st.session_state.set_nickname,
                "theme": st.session_state.set_theme,
                "temperature": st.session_state.set_temperature,
                "top_p": st.session_state.set_top_p,
                "max_tokens": st.session_state.set_max_tokens,
                "history_keep": st.session_state.set_history_keep,
                "compress_threshold": st.session_state.set_compress_threshold,
            })
            st.session_state.prefs = api.get_prefs()
            st.success("已保存")
            st.rerun()


@st.dialog("确认删除会话？")
def delete_confirm_dialog(cid: str, title: str):
    st.write(f"将删除「{title}」，此操作不可撤销。")
    cols = st.columns(2)
    if cols[0].button("删除", type="primary"):
        api.delete_conversation(cid)
        if st.session_state.current_cid == cid:
            st.session_state.current_cid = None
            st.session_state.messages = []
            st.session_state.current_title = ""
        st.rerun()
    if cols[1].button("取消"):
        st.rerun()


# ================ 侧边栏 ================
with st.sidebar:
    st.title("🤖 chatbot-plus")

    st.subheader("✨ 新建对话")
    task_options = {t["key"]: f"{t['icon']} {t['name']}" for t in st.session_state.tasks}
    st.selectbox("任务类型", list(task_options.keys()),
                 format_func=lambda k: task_options.get(k, k),
                 key="new_task")
    # 图片任务：模型由专用画图模型决定，隐藏/禁用文本模型选择意义不大，仅提示。
    _nt = next((t for t in st.session_state.tasks if t["key"] == st.session_state.new_task), None)
    if _nt and _nt.get("model") in ("image_gen", "image_edit"):
        st.caption("⚙️ 该任务使用专用画图模型，下方模型选项不生效。")
    st.selectbox("模型", st.session_state.models, key="new_model")
    if st.button("➕ 新建对话", use_container_width=True):
        new_conversation()

    st.divider()

    search = st.text_input("🔍 搜索会话", value="", key="conv_search")
    convs = api.list_conversations(search if search.strip() else None)

    st.subheader(f"历史会话（{len(convs)}）")
    for c in convs:
        row = st.columns([7, 1])
        prefix = "📌 " if c["pinned"] else ""
        active = c["id"] == st.session_state.current_cid
        if row[0].button(f"{prefix}{c['title']}", key=f"cv_{c['id']}",
                         use_container_width=True,
                         type="primary" if active else "secondary"):
            switch_conversation(c["id"])
            st.rerun()
        # 右侧「⋯」菜单：点击展开置顶 / 删除
        with row[1].popover("⋯", use_container_width=True, help="更多操作"):
            pin_label = "取消置顶" if c["pinned"] else "置顶"
            if st.button(pin_label, key=f"pin_{c['id']}", use_container_width=True):
                api.update_conversation(c["id"], pinned=0 if c["pinned"] else 1)
                st.rerun()
            if st.button("🗑 删除", key=f"del_{c['id']}", use_container_width=True):
                delete_confirm_dialog(c["id"], c["title"])
        # 标题下小字：任务图标 · 相对更新时间
        st.markdown(
            f"<div class='cp-conv-meta'>{_task_icon(c.get('task', ''))} · "
            f"{_rel_time(c.get('updated_at', ''))}</div>",
            unsafe_allow_html=True,
        )

    st.divider()
    render_settings()


# ================ 主区域 ================
if st.session_state.get("_attach_err"):
    st.error(f"📎 {st.session_state['_attach_err']}")
    del st.session_state["_attach_err"]
    
if st.session_state.current_cid:
    header = st.columns([7, 2, 1])
    # 切换会话时重置标题输入框
    if st.session_state.get("_title_cid") != st.session_state.current_cid:
        st.session_state["_title_cid"] = st.session_state.current_cid
        st.session_state["title_input"] = st.session_state.current_title

    def on_title_change():
        new_t = st.session_state.title_input.strip() or "新对话"
        api.update_conversation(st.session_state.current_cid, title=new_t)
        st.session_state.current_title = new_t

    header[0].text_input("标题", label_visibility="collapsed",
                         key="title_input", on_change=on_title_change)
    header[1].markdown(f"`{task_name(st.session_state.current_task)}`")

    with header[2].popover("⬇️", use_container_width=True, help="导出当前会话"):
        st.caption("导出当前会话")
        md = api.export_conversation(st.session_state.current_cid, "md")
        js = api.export_conversation(st.session_state.current_cid, "json")
        st.download_button("Markdown", data=md["content"],
                           file_name=md["filename"], mime="text/markdown",
                           use_container_width=True)
        st.download_button("JSON", data=js["content"],
                           file_name=f"{st.session_state.current_title}.json",
                           mime="application/json", use_container_width=True)
else:
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
            render_content(m["content"])
            info = []
            if m.get("model"):
                info.append(m["model"])
            if m.get("tokens"):
                info.append(f"{m['tokens']} tokens")
            if info:
                st.markdown(
                    "<div class='cp-meta'>"
                    + " · ".join(html.escape(i) for i in info)
                    + "</div>",
                    unsafe_allow_html=True,
                )
            if not st.session_state.streaming:
                # 操作栏：复制全文 + 重新生成（hover 才完整显现）
                ac = st.columns([1, 1, 6])
                ac[0].markdown(copy_chip_html(m["content"]), unsafe_allow_html=True)
                if ac[1].button("🔄", key=f"rg_{m['id']}", help="重新生成回复"):
                    handle_regen(m["id"])

# 编辑框
if st.session_state.editing_msg_id and not st.session_state.streaming:
    with st.container(border=True):
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

# 流式气泡（fragment）——只在流式时挂载，避免空闲时无谓的 0.3s 定时重跑与 fragment 警告
if st.session_state.streaming:
    streaming_fragment()

# 最近一次 token 用量
if st.session_state.get("last_usage"):
    u = st.session_state.last_usage
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

# 注入主文档脚本：复制委托、流式光标/停止胶囊、灵感卡片样式。
# 必须用 components.html（iframe 带 allow-scripts + allow-same-origin），st.html 会被 DOMPurify 清掉 <script>。
# 卡片样式同时作用于灵感问题与图片任务提示词模版（按按钮文本匹配）。
_sugg_for_cards = list(st.session_state.suggestions or [])
_sugg_for_cards += list(st.session_state.get("_tpl_titles") or [])
components.html(_cp_components_js(_sugg_for_cards), height=0)

# 聊天输入占位符随任务调整：图片编辑提示上传原图
_cto = _current_task_obj()
_in_ph = ("描述修改要求（需先上传原图）…"
          if (_cto and _cto.get("key") == "image_edit")
          else "输入消息开始聊天…")

prompt = st.chat_input(_in_ph, accept_file="multiple",
                       file_type=_ATTACH_TYPES, disabled=chat_disabled)
if prompt and not chat_disabled:
    # accept_file="multiple" 时返回 ChatInputValue（含 .text / .files）
    if isinstance(prompt, str):
        text, files = prompt, []
    else:
        text = prompt.text or ""
        files = prompt.files or []
    text = text.strip()
    # 上传附件（若有），失败则提示且仅发文本
    file_metas = []
    if files:
        try:
            file_metas = api.upload_files(list(files))
        except Exception as e:
            st.session_state["_attach_err"] = f"附件上传失败：{e}"
            st.rerun()
    if text or file_metas:
        ensure_conversation()
        start_streaming(text, regenerate=False, file_metas=file_metas)
