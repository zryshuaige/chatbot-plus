'''渲染工具：把含代码块的 markdown 拆开渲染（prose 用 markdown，代码用 st.code 自带复制），
以及把后端头像 URL 转成 Streamlit 可用的 PIL 图像。
用户消息用自定义 HTML 气泡（靠右），助手消息沿用 st.chat_message（靠左，保留代码复制）。'''
import base64
import html as _html
import json
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


@st.cache_data(show_spinner=False)
def avatar_data_url(avatar_path: str, role: str) -> str:
    """返回可在 <img src=...> 使用的 data URL；无头像则返回空串（由调用方用 emoji 兜底）。"""
    if not avatar_path:
        return ""
    try:
        url = avatar_path if avatar_path.startswith("http") else \
            f"http://127.0.0.1:{_backend_port()}{avatar_path}"
        data = _fetch_avatar_bytes(url)
        ext = avatar_path.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/png")
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"
    except Exception:
        return ""


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


# ---------------- 用户气泡（自定义 HTML，靠右） ----------------
_FENCE_RE = re.compile(r"```([^\n`]*)\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")


def _user_text_to_html(text: str) -> str:
    """用户消息的轻量 markdown：转义后处理代码块/行内代码/粗体/换行。"""
    out: list[str] = []
    pos = 0
    for m in _FENCE_RE.finditer(text):
        if m.start() > pos:
            out.append(_render_inline(text[pos:m.start()]))
        code = _html.escape(m.group(2))
        out.append(f"<pre><code>{code}</code></pre>")
        pos = m.end()
    if pos < len(text):
        out.append(_render_inline(text[pos:]))
    return "".join(out)


def _render_inline(text: str) -> str:
    s = _html.escape(text)
    s = _BOLD_RE.sub(r"<strong>\1</strong>", s)
    s = _INLINE_CODE_RE.sub(
        lambda m: f'<code>{_html.escape(m.group(1))}</code>', s
    )
    s = s.replace("\n", "<br>")
    return s


def _normalize_attachments(attachments) -> list:
    """把附件规整成 list[dict]：兼容后端返回字符串、None、或非 dict 元素。"""
    if not attachments:
        return []
    if isinstance(attachments, str):
        try:
            attachments = json.loads(attachments)
        except (ValueError, TypeError):
            return []
    if not isinstance(attachments, list):
        return []
    return [a for a in attachments if isinstance(a, dict)]


def _file_url(file_id: str, inline: bool = False) -> str:
    """后端下载接口的完整 URL。inline=True 用于图片直接显示（Content-Disposition: inline）。"""
    if not file_id:
        return ""
    qs = "?inline=1" if inline else ""
    return f"http://127.0.0.1:{_backend_port()}/files/{file_id}{qs}"


def _attach_chips(attachments) -> str:
    """渲染附件区：图片显示可点击缩略图（点开看原图），其他文件显示可点击文件名 chip（点击下载）。"""
    atts = _normalize_attachments(attachments)
    if not atts:
        return ""
    items: list[str] = []
    for a in atts:
        filename = a.get("filename", "文件")
        kind = a.get("kind", "")
        fid = a.get("file_id", "")
        safe = _html.escape(filename)
        if kind == "image" and fid:
            url = _file_url(fid, inline=True)
            items.append(
                f'<a class="cp-attach-img" href="{url}" target="_blank" rel="noopener" title="{safe}">'
                f'<img src="{url}" alt="{safe}" loading="lazy"></a>'
            )
        else:
            dl = _file_url(fid) if fid else ""
            if dl:
                items.append(
                    f'<a class="cp-attach-chip" href="{dl}" target="_blank" rel="noopener" '
                    f'download="{safe}">📎 {safe}</a>'
                )
            else:
                items.append(f'<span class="cp-attach-chip">📎 {safe}</span>')
    return f'<div class="cp-attaches">{"".join(items)}</div>'


def attachments_html(attachments) -> str:
    """渲染附件区 HTML（图片缩略图 + 文件 chip），助手/用户气泡复用。
    无附件返回空串。"""
    return _attach_chips(attachments)


def user_bubble_html(content: str, avatar_path: str,
                     attachments=None) -> str:
    """渲染一条靠右的用户气泡（avatar + 气泡 + 附件 chip）。"""
    data_url = avatar_data_url(avatar_path, "user")
    if data_url:
        avatar = f'<img src="{data_url}" style="width:100%;height:100%;object-fit:cover;">'
    else:
        avatar = DEFAULT_AVATARS.get("user", "🦞")
    body = _user_text_to_html(content or "")
    chips = _attach_chips(attachments)
    return (
        '<div class="cp-msg-row user">'
        f'<div class="cp-bubble user">{body}{chips}</div>'
        f'<div class="cp-avatar">{avatar}</div>'
        '</div>'
    )


def copy_chip_html(content: str) -> str:
    """助手消息的「复制全文」按钮：内容以 base64 存入 data-b64，
    由全局事件委托（components.html 注入的脚本）拦截 .cp-act 点击并解码写入剪贴板。
    不用内联 onclick——st.markdown 的 DOMPurify 会清掉 on* 事件属性。"""
    b64 = base64.b64encode((content or "").encode("utf-8")).decode("ascii")
    return (
        '<div class="cp-actions">'
        f'<button class="cp-act" type="button" data-b64="{b64}" title="复制全文">📋 复制</button>'
        '</div>'
    )

