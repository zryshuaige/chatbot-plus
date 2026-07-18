'''chatbot-plus 前端：Streamlit 多轮聊天应用。
特性：任务系统提示词、头像、主题、历史自动命名、上下文压缩、
流式可中断、重生成/编辑、多模型+token用量、会话搜索/导出。'''
from datetime import timedelta

import queue
import streamlit as st

import api_client as api
from themes import theme_css, theme_keys, theme_name, DEFAULT_THEME
from render import render_content, load_avatar

st.set_page_config(page_title="chatbot-plus", page_icon="🤖", layout="wide",
                   initial_sidebar_state="expanded")


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
        "last_usage": None,        # 最近一次 token 用量（展示）
        "editing_msg_id": None,    # 正在编辑的用户消息 id
        "prefs_loaded": False,
        "new_task": "daily",       # 侧边栏“新建对话”用的任务
        "new_model": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


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
         "tokens": m.get("tokens", 0), "model": m.get("model", "")}
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
    task = st.session_state.new_task
    model = st.session_state.new_model or prefs.get("default_model") or st.session_state.default_model
    data = api.create_conversation(task, model)
    switch_conversation(data["id"])
    st.rerun()


def task_name(key: str) -> str:
    for t in st.session_state.tasks:
        if t["key"] == key:
            return f"{t['icon']} {t['name']}"
    return key


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


def start_streaming(query: str, regenerate: bool = False):
    cid = st.session_state.current_cid
    if not cid:
        return
    if not regenerate:
        # 乐观加入用户消息（真实 id 由 start 事件回填）
        st.session_state.messages.append(
            {"id": None, "role": "user", "content": query, "tokens": 0, "model": ""}
        )
    q, stop = api.stream_chat_threaded(
        cid, query, regenerate=regenerate,
        temperature=prefs.get("temperature"), top_p=prefs.get("top_p"),
        max_tokens=prefs.get("max_tokens"),
    )
    st.session_state.stream_queue = q
    st.session_state.stop_event = stop
    st.session_state.stream_buffer = ""
    st.session_state.stream_usage = None
    st.session_state.stream_error = None
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
    if buf.strip():
        saved = api.save_message(cid, "assistant", buf, tokens=tokens, model=model)
        st.session_state.messages.append(
            {"id": saved["id"], "role": "assistant", "content": buf,
             "tokens": tokens, "model": model}
        )
    st.session_state.last_usage = usage
    st.session_state.streaming = False
    st.session_state.stream_queue = None
    st.session_state.stop_event = None
    st.session_state.stream_buffer = ""
    st.session_state.stream_usage = None
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
        elif t == "usage":
            st.session_state.stream_usage = evt
        elif t in ("done", "stopped", "error"):
            if t == "error":
                st.session_state.stream_error = evt.get("message", "生成失败")
            finalized = True
            break

    # 渲染当前进度的助手气泡
    with st.chat_message("assistant", avatar="🤖"):
        buf = st.session_state.stream_buffer
        render_content(buf or "生成中…")
        if st.button("⏹ 停止生成", key="stop_stream_btn"):
            stop_event.set()

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


def render_settings():
    """偏好设置：昵称、头像、主题、采样参数、压缩策略。"""
    with st.expander("⚙️ 个人化设置"):
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
                     key="set_theme")

        st.markdown("**采样参数**")
        st.slider("温度 temperature", 0.0, 1.0, float(prefs.get("temperature", 0.5)),
                  0.05, key="set_temperature")
        st.slider("采样概率 top_p", 0.0, 1.0, float(prefs.get("top_p", 0.5)),
                  0.05, key="set_top_p")
        st.slider("最大词源数 max_tokens", 64, 4096,
                  int(prefs.get("max_tokens", 1024)), 64, key="set_max_tokens")

        st.markdown("**上下文压缩**")
        st.slider("保留最近 N 轮原文", 1, 12,
                  int(prefs.get("history_keep", 4)), 1, key="set_history_keep")
        st.slider("压缩触发阈值（估算 token）", 800, 8000,
                  int(prefs.get("compress_threshold", 3000)), 100, key="set_compress_threshold")

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
    st.selectbox("模型", st.session_state.models, key="new_model")
    if st.button("➕ 新建对话", use_container_width=True):
        new_conversation()

    st.divider()

    search = st.text_input("🔍 搜索会话", value="", key="conv_search")
    convs = api.list_conversations(search if search.strip() else None)

    st.subheader(f"历史会话（{len(convs)}）")
    for c in convs:
        cols = st.columns([6, 1, 1])
        prefix = "📌 " if c["pinned"] else ""
        active = c["id"] == st.session_state.current_cid
        if cols[0].button(f"{prefix}{c['title']}", key=f"cv_{c['id']}",
                          use_container_width=True,
                          type="primary" if active else "secondary"):
            switch_conversation(c["id"])
            st.rerun()
        if cols[1].button("📌" if not c["pinned"] else "📍", key=f"pin_{c['id']}"):
            api.update_conversation(c["id"], pinned=0 if c["pinned"] else 1)
            st.rerun()
        if cols[2].button("🗑", key=f"del_{c['id']}"):
            delete_confirm_dialog(c["id"], c["title"])

    st.divider()
    render_settings()


# ================ 主区域 ================
st.title("💬 多轮聊天（升级版）")

if st.session_state.current_cid:
    header = st.columns([6, 2, 1, 1])
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

    exp_md = header[2].button("📝MD")
    exp_json = header[3].button("🗂JSON")
    if exp_md:
        data = api.export_conversation(st.session_state.current_cid, "md")
        st.download_button("下载 Markdown", data=data["content"],
                           file_name=data["filename"], mime="text/markdown")
    if exp_json:
        data = api.export_conversation(st.session_state.current_cid, "json")
        st.download_button("下载 JSON", data=data["content"],
                           file_name=f"{st.session_state.current_title}.json",
                           mime="application/json")
else:
    st.info("👈 在左侧点击「新建对话」开始聊天，或直接在下方输入会自动创建。")

# 渲染历史消息
user_avatar = load_avatar(prefs.get("avatar_path", ""), "user")
for m in st.session_state.messages:
    with st.chat_message(m["role"],
                         avatar=user_avatar if m["role"] == "user" else "🤖"):
        render_content(m["content"])
        meta = st.container()
        mcols = meta.columns([2, 1, 1])
        info = []
        if m["role"] == "assistant" and m.get("model"):
            info.append(m["model"])
        if m.get("tokens"):
            info.append(f"{m['tokens']} tokens")
        mcols[0].caption(" · ".join(info) if info else " ")
        if m["role"] == "assistant" and not st.session_state.streaming:
            if mcols[1].button("🔄", key=f"rg_{m['id']}", help="重新生成"):
                handle_regen(m["id"])
        if m["role"] == "user" and not st.session_state.streaming:
            if mcols[2].button("✏️", key=f"ed_{m['id']}", help="编辑后重发"):
                st.session_state.editing_msg_id = m["id"]
                st.session_state["edit_text"] = m["content"]
                st.rerun()

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
    note = (f"最近用量：prompt {u.get('prompt_tokens', 0)} + "
            f"completion {u.get('completion_tokens', 0)} = "
            f"{u.get('total_tokens', 0)} tokens")
    if u.get("compressed"):
        note += "  ·  已触发上下文压缩"
    st.caption(note)

# 聊天输入
disabled = st.session_state.streaming or bool(st.session_state.editing_msg_id)
user_input = st.chat_input("输入消息开始聊天…", disabled=disabled)
if user_input and not disabled:
    ensure_conversation()
    start_streaming(user_input, regenerate=False)
