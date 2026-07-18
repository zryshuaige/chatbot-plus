'''渲染工具：把含代码块的 markdown 拆开渲染（prose 用 markdown，代码用 st.code 自带复制），
以及把后端头像 URL 转成 Streamlit 可用的 PIL 图像。'''
import re
from io import BytesIO

import requests

import streamlit as st

# 代码块正则：```lang\n 代码 ```
_CODE_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)

# 默认 emoji 头像
DEFAULT_AVATARS = {"user": "🦞", "assistant": "🍀"}


def split_segments(text: str):
    """把文本切成 ('text', str) 与 ('code', (lang, code)) 片段序列。"""
    pos = 0
    for m in _CODE_RE.finditer(text):
        if m.start() > pos:
            yield ("text", text[pos:m.start()])
        lang = (m.group(1) or "").strip()
        yield ("code", (lang, m.group(2)))
        pos = m.end()
    if pos < len(text):
        yield ("text", text[pos:])


def render_content(text: str):
    """在当前容器内渲染 markdown+代码块。流式时可直接用 st.markdown 整段渲染。"""
    has_code = "```" in text
    if not has_code:
        st.markdown(text)
        return
    for kind, val in split_segments(text):
        if kind == "text":
            seg = val.strip("\n")
            if seg:
                st.markdown(seg)
        else:
            lang, code = val
            # st.code 自带复制按钮与语法高亮
            st.code(code, language=lang or None)


@st.cache_data(show_spinner=False)
def _fetch_avatar_bytes(url: str) -> bytes:
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return r.content


def load_avatar(avatar_path: str, role: str):
    """返回 chat_message 可用的 avatar：上传的图片(PIL) 或 emoji。
    失败时回退到默认 emoji。"""
    if not avatar_path:
        return DEFAULT_AVATARS.get(role, "🤖")
    try:
        url = avatar_path if avatar_path.startswith("http") else \
            f"http://127.0.0.1:{_backend_port()}{avatar_path}"
        data = _fetch_avatar_bytes(url)
        from PIL import Image
        return Image.open(BytesIO(data))
    except Exception:
        return DEFAULT_AVATARS.get(role, "🤖")


def _backend_port() -> str:
    import os
    return os.getenv("BACKEND_PORT", "8002")
