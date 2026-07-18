'''UI 主题预设：通过注入 CSS 实现「简约浅色 / 深色静谧 / 护眼绿 / 活力紫」四套主题。
所有样式合并进单个 <style> 块（避免多 style 块被 Streamlit 当作纯文本渲染），
主题只覆盖 CSS 变量与少量组件规则，覆盖段放在最后以确保级联生效。'''

# 默认 CSS 变量
_ROOT_DEFAULTS = """
:root {
  --bg: #f7f8fa;
  --sidebar-bg: #ffffff;
  --surface: #ffffff;
  --text: #1f2329;
  --text-muted: #8a9099;
  --border: #eceef1;
  --accent: #4f6ef7;
  --accent-soft: #eef1fe;
  --assistant-bubble-bg: #ffffff;
  --assistant-bubble-fg: #1f2329;
  --user-bubble-bg: #4f6ef7;
  --user-bubble-fg: #ffffff;
  --code-bg: #f2f3f5;
  --shadow: 0 1px 2px rgba(20,24,35,.04), 0 4px 16px rgba(20,24,35,.04);
  --radius: 14px;
}
"""

# 组件样式（引用上面的变量）。各主题可在 override 段覆盖变量或规则。
_COMPONENT_CSS = """
/* ---------- 全局排版 ---------- */
html, body, .stApp {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
.stApp { background: var(--bg); color: var(--text); }
#root, .stApp { padding-top: 1rem; }

/* ---------- 侧边栏 ---------- */
section[data-testid="stSidebar"] {
  background: var(--sidebar-bg);
  border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p { color: var(--text); }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { font-weight: 600; letter-spacing: .2px; }

/* ---------- 主标题 / 分隔 ---------- */
.stApp h1 { font-weight: 650; letter-spacing: .3px; }
.stApp h3 { font-weight: 600; }
hr { border-color: var(--border) !important; opacity: .8; }

/* ---------- 按钮：克制的高级感 ---------- */
.stButton > button {
  border-radius: 10px !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;
  font-weight: 500 !important;
  padding: .3rem .7rem !important;
  font-size: .86rem !important;
  transition: all .15s ease !important;
  box-shadow: none !important;
}
.stButton > button:hover {
  border-color: var(--accent) !important;
  color: var(--accent) !important;
  background: var(--accent-soft) !important;
}
/* primary 按钮：用 accent 实色 */
.stButton > button[kind="primary"] {
  background: var(--accent) !important;
  color: #fff !important;
  border-color: var(--accent) !important;
}
.stButton > button[kind="primary"]:hover {
  filter: brightness(1.05);
  color: #fff !important;
  background: var(--accent) !important;
}

/* ---------- 输入框 ---------- */
.stTextArea textarea, .stTextInput input {
  border-radius: 10px !important;
  border-color: var(--border) !important;
  background: var(--surface) !important;
}
.stTextArea textarea:focus, .stTextInput input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px var(--accent-soft) !important;
}

/* ---------- 聊天输入（底部） ---------- */
[data-testid="stChatInput"] textarea {
  border-radius: 16px !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  box-shadow: var(--shadow) !important;
}

/* ---------- 助手气泡（st.chat_message） ---------- */
[data-testid="stChatMessage"] {
  background: var(--assistant-bubble-bg) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  box-shadow: var(--shadow) !important;
  padding: 1rem 1.1rem !important;
  max-width: 82% !important;
  margin: .35rem 0 .35rem 0 !important;
}
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarContainer"] {
  width: 2.2rem !important; height: 2.2rem !important;
}
[data-testid="stChatMessage"] * { color: var(--assistant-bubble-fg); }
[data-testid="stChatMessage"] a { color: var(--accent); }

/* 代码块 */
.stCodeBlock, .stCodeBlock pre {
  border-radius: 10px !important;
  background: var(--code-bg) !important;
}
.stCodeBlock { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }

/* ---------- 用户气泡（自定义 HTML，靠右） ---------- */
.cp-msg-row { display: flex; width: 100%; align-items: flex-end; gap: .55rem; margin: .5rem 0 .15rem; }
.cp-msg-row.user { justify-content: flex-end; }
.cp-msg-row .cp-avatar {
  width: 2.2rem; height: 2.2rem; border-radius: 50%; flex: 0 0 2.2rem;
  display: flex; align-items: center; justify-content: center; font-size: 1.15rem;
  background: var(--accent-soft); overflow: hidden;
}
.cp-msg-row.user .cp-avatar { order: 2; }
.cp-bubble {
  max-width: 72%; padding: .62rem .9rem; border-radius: var(--radius);
  line-height: 1.6; word-break: break-word; box-shadow: var(--shadow);
  font-size: .95rem;
}
.cp-bubble.user {
  background: var(--user-bubble-bg); color: var(--user-bubble-fg);
  border-bottom-right-radius: 4px;
}
.cp-bubble pre {
  background: rgba(0,0,0,.18); color: var(--user-bubble-fg);
  padding: .6rem .75rem; border-radius: 8px; overflow-x: auto; margin: .3rem 0;
  font-size: .85rem;
}
.cp-bubble code { font-family: "SF Mono", Menlo, Consolas, monospace; }
.cp-attach-chip {
  display: inline-flex; align-items: center; gap: .3rem;
  font-size: .78rem; padding: .15rem .55rem; margin: .15rem .25rem 0 0;
  border-radius: 999px; background: rgba(0,0,0,.06); opacity: .92;
}
.cp-msg-row.user .cp-attach-chip { background: rgba(255,255,255,.22); }

/* 消息间留白，避免按钮挤在一起 */
[data-testid="stChatMessage"] + div,
.cp-msg-row + div { margin-top: .15rem; }

/* 滚动条 */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 8px; }
::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

/* ============ 流式输出动画 ============ */
/* 思考中三点跳动 */
.cp-thinking { display: inline-flex; gap: 7px; align-items: center; padding: .35rem .1rem; }
.cp-thinking span {
  width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
  display: inline-block; opacity: .45; animation: cp-bounce 1.2s infinite ease-in-out both;
}
.cp-thinking span:nth-child(2) { animation-delay: .15s; }
.cp-thinking span:nth-child(3) { animation-delay: .30s; }
@keyframes cp-bounce { 0%,80%,100% { transform: scale(.55); opacity: .4; } 40% { transform: scale(1); opacity: 1; } }
/* 流式光标：气泡末尾闪烁 */
[data-testid="stChatMessage"].cp-streaming .stMarkdown:last-of-type p::after {
  content: ""; display: inline-block; width: .55em; height: 1.05em; background: var(--accent);
  margin-left: 3px; vertical-align: -.18em; border-radius: 1px;
  animation: cp-blink 1s steps(2, start) infinite;
}
@keyframes cp-blink { 0%,50% { opacity: 1; } 50.01%,100% { opacity: 0; } }
/* 流式气泡入场 */
[data-testid="stChatMessage"].cp-streaming,
[data-testid="stChatMessage"].cp-thinking-bubble { animation: cp-pop .22s ease; }
@keyframes cp-pop { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
/* 停止按钮：胶囊 + 脉冲圆点 */
.cp-stop-btn {
  border-radius: 999px !important; padding: .28rem .9rem !important;
  font-size: .82rem !important; border: 1px solid var(--border) !important;
  background: var(--surface) !important; color: var(--text) !important;
  display: inline-flex !important; align-items: center !important; gap: .4rem !important;
}
.cp-stop-btn::before {
  content: ""; width: 8px; height: 8px; border-radius: 50%; background: #e5484d;
  animation: cp-pulse 1.2s infinite ease-in-out;
}
@keyframes cp-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(229,72,77,.45); } 50% { box-shadow: 0 0 0 5px rgba(229,72,77,0); } }

/* ============ 助手消息操作栏 ============ */
.cp-actions { display: inline-flex; align-items: center; gap: .35rem; }
.cp-act {
  font-size: .78rem; color: var(--text-muted); background: transparent; border: none;
  padding: .25rem .55rem; border-radius: 8px; cursor: pointer; display: inline-flex;
  align-items: center; gap: .3rem; transition: all .15s ease;
}
.cp-act:hover { background: var(--accent-soft); color: var(--accent); }
.cp-act.cp-copied { color: #2f9e44; }
/* hover 才显示整条操作栏（:has 作用域；不支持 :has 时退化为常显） */
[data-testid="stChatMessage"] [data-testid="stHorizontalBlock"]:has(.cp-actions) { opacity: .5; transition: opacity .18s ease; }
[data-testid="stChatMessage"]:hover [data-testid="stHorizontalBlock"]:has(.cp-actions) { opacity: 1; }
.cp-meta { font-size: .74rem; color: var(--text-muted); text-align: right; opacity: .85; }

/* ============ token 用量胶囊 ============ */
.cp-usage { display: flex; flex-wrap: wrap; gap: .4rem; padding: .25rem 0; }
.cp-pill {
  display: inline-flex; align-items: center; gap: .3rem; font-size: .74rem;
  padding: .2rem .6rem; border-radius: 999px; background: var(--accent-soft);
  color: var(--text); border: 1px solid var(--border);
}
.cp-pill.cp-pill-accent { background: var(--accent); color: #fff; border-color: var(--accent); }
.cp-pill.cp-pill-warn { background: rgba(229,159,0,.14); color: #b58105; border-color: rgba(229,159,0,.3); }

/* ============ 欢迎页 ============ */
.cp-hero { text-align: center; padding: 2.4rem 1rem 1.2rem; }
.cp-hero-logo {
  width: 64px; height: 64px; border-radius: 18px; margin: 0 auto .9rem;
  display: flex; align-items: center; justify-content: center; font-size: 2rem;
  background: var(--accent-soft); border: 1px solid var(--border); box-shadow: var(--shadow);
}
.cp-hero h2 { margin: 0 0 .35rem; font-weight: 650; }
.cp-hero p { margin: 0; opacity: .65; font-size: .92rem; }
/* 灵感卡片：JS 按文本匹配给二级按钮打 cp-sugg-card 类 */
.cp-sugg-card {
  text-align: left !important; height: auto !important; min-height: 60px !important;
  padding: .8rem 1rem !important; border-radius: 14px !important;
  border: 1px solid var(--border) !important; background: var(--surface) !important;
  color: var(--text) !important; white-space: normal !important; line-height: 1.4 !important;
  transition: all .15s ease !important;
}
.cp-sugg-card:hover { transform: translateY(-2px); border-color: var(--accent) !important; box-shadow: var(--shadow) !important; }
.cp-sugg-ic { margin-right: .5rem; }

/* ============ 侧边栏会话项小字 ============ */
.cp-conv-meta { font-size: .7rem; color: var(--text-muted); padding: 0 .15rem .3rem; margin-top: -.2rem; opacity: .8; }

/* ============ JS 注入用 iframe（components.html, height=0）：确保不占版面 ============ */
[data-testid="stIFrame"] { min-height: 0 !important; line-height: 0; }
[data-testid="stIFrame"] iframe { border: 0; }
"""

# 各主题覆盖段（变量 + 少量组件规则），放在组件样式之后以生效
_THEME_OVERRIDES = {
    "minimal": {
        "name": "简约浅色",
        "css": "",  # 用默认值
    },
    "dark": {
        "name": "深色静谧",
        "css": """
        :root {
          --bg: #0f1419;
          --sidebar-bg: #131922;
          --surface: #1a212c;
          --text: #e6e8eb;
          --text-muted: #8b94a1;
          --border: #262e3a;
          --accent: #6b8afd;
          --accent-soft: #1e2536;
          --assistant-bubble-bg: #1a212c;
          --assistant-bubble-fg: #e6e8eb;
          --user-bubble-bg: #4f6ef7;
          --user-bubble-fg: #ffffff;
          --code-bg: #11161e;
          --shadow: 0 1px 2px rgba(0,0,0,.25), 0 6px 20px rgba(0,0,0,.28);
        }
        .stApp { background: linear-gradient(180deg, #0f1419 0%, #121822 100%); }
        .cp-bubble pre { background: rgba(255,255,255,.08); }
        .cp-attach-chip { background: rgba(255,255,255,.08); }
        """,
    },
    "green": {
        "name": "护眼绿",
        "css": """
        :root {
          --bg: #f1f5ec;
          --sidebar-bg: #e9efe0;
          --surface: #ffffff;
          --text: #2b3326;
          --text-muted: #7d8a72;
          --border: #d4dec4;
          --accent: #4f9d5a;
          --accent-soft: #e4eede;
          --assistant-bubble-bg: #ffffff;
          --assistant-bubble-fg: #2b3326;
          --user-bubble-bg: #4f9d5a;
          --user-bubble-fg: #ffffff;
          --code-bg: #e7ecdd;
          --shadow: 0 1px 2px rgba(40,55,30,.04), 0 4px 16px rgba(40,55,30,.05);
        }
        """,
    },
    "purple": {
        "name": "活力紫",
        "css": """
        :root {
          --bg: #faf7ff;
          --sidebar-bg: #f3edff;
          --surface: #ffffff;
          --text: #2d2440;
          --text-muted: #8b80a6;
          --border: #e6dbff;
          --accent: #7c5cff;
          --accent-soft: #efe9ff;
          --assistant-bubble-bg: #ffffff;
          --assistant-bubble-fg: #2d2440;
          --user-bubble-bg: #7c5cff;
          --user-bubble-fg: #ffffff;
          --code-bg: #f1ecff;
          --shadow: 0 1px 2px rgba(60,40,90,.04), 0 4px 16px rgba(60,40,90,.06);
        }
        .stApp { background: linear-gradient(180deg, #faf7ff 0%, #f3edff 100%); }
        """,
    },
}

DEFAULT_THEME = "minimal"


def theme_keys() -> list[str]:
    return list(_THEME_OVERRIDES.keys())


def theme_name(key: str) -> str:
    return _THEME_OVERRIDES.get(key, _THEME_OVERRIDES[DEFAULT_THEME])["name"]


def theme_css(key: str) -> str:
    t = _THEME_OVERRIDES.get(key, _THEME_OVERRIDES[DEFAULT_THEME])
    # 单个 <style> 块：默认变量 -> 组件样式 -> 主题覆盖（覆盖段在后，级联生效）
    return f"<style>\n{_ROOT_DEFAULTS}\n{_COMPONENT_CSS}\n{t['css']}\n</style>"
