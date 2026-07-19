'''UI 主题预设：通过注入 CSS 实现「简约浅色 / 深色静谧 / 护眼绿 / 活力紫」四套主题。
所有样式合并进单个 <style> 块（避免多 style 块被 Streamlit 当作纯文本渲染），
主题只覆盖 CSS 变量与少量组件规则，覆盖段放在最后以确保级联生效。'''

# 默认 CSS 变量：颜色 + 动效令牌 + 材质令牌 + 排版基础
# 动效曲线/时长取自 AUDIT.md（不近似）：入场用 ease-out，屏内移动用 ease-in-out，抽屉用 ease-drawer。
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

  /* ---- 动效令牌 ---- */
  --ease-out: cubic-bezier(0.23, 1, 0.32, 1);      /* 入场/反馈默认：起手快，落得稳 */
  --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);  /* 屏内移动 A->B */
  --ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);   /* iOS 抽屉曲线 */
  --dur-press: 160ms;   /* 按压反馈 100–160ms */
  --dur-pop: 200ms;     /* 小型入场/弹层 125–200ms */
  --dur-dock: 240ms;    /* 抽屉/坞 200–500ms */

  /* ---- 材质令牌：半透明层（侧边栏底部区/输入坞/粘性顶栏） ---- */
  --material-bg: rgba(255, 255, 255, 0.66);
  --material-blur: blur(20px) saturate(180%);
  --hairline: rgba(255, 255, 255, 0.5);  /* 材质顶端的「高光边」，模拟光打在材质上 */
}
"""

# 组件样式（引用上面的变量）。各主题可在 override 段覆盖变量或规则。
_COMPONENT_CSS = """
/* ---------- 全局排版 ---------- */
/* 字距随尺寸变化（Apple）：大字负字距 + 紧行高，正文接近 0，小字微正字距易读。
   font-optical-sizing 让系统字随尺寸改变字形（自带 optical sizing / tracking 表）。 */
html, body, .stApp {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
               "Hiragino Sans GB", "Microsoft YaHei", Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  font-optical-sizing: auto;
  letter-spacing: 0;            /* 正文：接近 0 */
  line-height: 1.5;             /* 正文：舒适行高 */
}
.stApp { background: var(--bg); color: var(--text); }
#root, .stApp { padding-top: 1rem; }

/* ---------- 侧边栏 ---------- */
/* 右缘用渐隐阴影替代硬边框（Apple：滚动边缘效果，而非硬分隔线），仅当内容滚过时可见。 */
section[data-testid="stSidebar"] {
  background: var(--sidebar-bg);
  border-right: none;
  box-shadow: inset -10px 0 8px -8px rgba(0,0,0,.06);
}
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p { color: var(--text); }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { font-weight: 600; letter-spacing: -0.01em; }

/* 侧边栏底部固定区：把「个人信息 / 参数设置」钉在侧边栏底部，历史会话在其上方滚动。
   用 st.container() + .cp-bottom-anchor 标记底部区；嵌套 stVerticalBlock 选择器
   （[stVerticalBlock] [stVerticalBlock]）只命中容器自身，不误伤根容器导致整栏不滚动。 */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"]:has(.cp-bottom-anchor) {
  position: sticky; bottom: 0; z-index: 2;
  background: var(--material-bg);
  backdrop-filter: var(--material-blur);
  -webkit-backdrop-filter: var(--material-blur);
  margin-top: .4rem; padding-top: .4rem;
  border-top: 1px solid var(--hairline);
}
/* 底部区内部展开器不要额外外边距，紧凑些 */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"]:has(.cp-bottom-anchor) details {
  margin-top: .2rem;
}

/* ---------- 主标题 / 分隔 ---------- */
.stApp h1 { font-weight: 650; letter-spacing: -0.02em; line-height: 1.08; }  /* 大字：负字距 + 紧行高 */
.stApp h3 { font-weight: 600; letter-spacing: -0.01em; }
hr { border-color: var(--border) !important; opacity: .8; }

/* ---------- 文本色归一化（深色主题可读性的关键修复）----------
   Streamlit 用 styled-components 把浅色主题默认文本色（#31333F）直接内联到元素上，
   不走 CSS 变量；仅靠 .stApp{color} 的级联穿不透这些显式着色，导致深色背景下
   标题/正文/说明/标签一片看不清。这里按 data-testid 精准覆盖到 Streamlit 自有容器，
   使其跟随各主题 --text / --text-muted。
   只命中 Streamlit 容器（stHeading/stMarkdownContainer/...），不触碰 .cp-* 自定义组件，
   避免误伤气泡/胶囊/思考点等已有配色。!important 是为压过 styled-components 的内联色。 */
[data-testid="stHeading"],
[data-testid="stHeading"] h1, [data-testid="stHeading"] h2,
[data-testid="stHeading"] h3, [data-testid="stHeading"] h4,
[data-testid="stHeading"] h5, [data-testid="stHeading"] h6,
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] ul,
[data-testid="stMarkdownContainer"] ol,
[data-testid="stMarkdownContainer"] blockquote,
[data-testid="stMarkdownContainer"] strong,
[data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3, [data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] h5, [data-testid="stMarkdownContainer"] h6,
[data-testid="stMarkdownContainer"] td, [data-testid="stMarkdownContainer"] th,
[data-testid="stText"],
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
[data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stMetricDelta"],
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary span {
  color: var(--text) !important;
}
/* 说明文字（st.caption / 模型简介等）：次要色，保持层级但仍可读 */
[data-testid="stCaptionContainer"] { color: var(--text-muted) !important; }
/* 链接保持强调色，不被上面 var(--text) 盖掉 */
[data-testid="stMarkdownContainer"] a { color: var(--accent) !important; }

/* ---------- 粘性顶栏（会话标题/任务/导出）：半透明材质 ----------
   app.py 用 st.container()+.cp-topbar-anchor 标记顶栏；:has 命中该容器并钉在主区顶部。
   Apple wayfinding：始终知道「我在哪个会话」，消息从下方滚入时透出材质。 */
section[data-testid="stMain"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"]:has(.cp-topbar-anchor) {
  position: sticky; top: 0; z-index: 5;
  background: var(--material-bg);
  backdrop-filter: var(--material-blur);
  -webkit-backdrop-filter: var(--material-blur);
  border-bottom: 1px solid var(--hairline);
  padding: .5rem 0 .35rem;
  margin: 0 0 .5rem;
}

/* ---------- 按钮：克制的高级感 ---------- */
/* transition 拆成具体属性（AUDIT.md：`transition: all` 会把非合成属性拖上主线程）；
   加 :active 按压反馈（Apple：反馈必须在 pointer-down 当下发生，等 release 才「死」）。 */
.stButton > button {
  border-radius: 10px !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;
  font-weight: 500 !important;
  padding: .3rem .7rem !important;
  font-size: .86rem !important;
  transition: transform var(--dur-press) var(--ease-out),
              border-color .15s var(--ease-out),
              color .15s var(--ease-out),
              background .15s var(--ease-out),
              filter .15s var(--ease-out) !important;
  box-shadow: none !important;
}
.stButton > button:hover {
  border-color: var(--accent) !important;
  color: var(--accent) !important;
  background: var(--accent-soft) !important;
}
/* 按压：轻微缩小，0.97 在克制区间 0.95–0.98 内 */
.stButton > button:active { transform: scale(0.97); }
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
.stButton > button[kind="primary"]:active { transform: scale(0.97); }

/* ---------- 输入框 ---------- */
.stTextArea textarea, .stTextInput input,
[data-testid="stSelectbox"] input {
  border-radius: 10px !important;
  border-color: var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;           /* 深色主题下输入文字跟随 --text，否则是 #31333F 看不清 */
}
.stTextArea textarea::placeholder, .stTextInput input::placeholder,
[data-testid="stSelectbox"] input::placeholder {
  color: var(--text-muted) !important; opacity: 1;   /* placeholder 用次要色 */
}
.stTextArea textarea:focus, .stTextInput input:focus,
[data-testid="stSelectbox"] input:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px var(--accent-soft) !important;
}

/* ---------- 聊天输入坞（底部，半透明材质） ---------- */
/* Apple：浮动功能性层用半透明材质，消息从下方滚入时透出，
   而非吃掉固定一条的不透明栏。材质顶端留高光边模拟光打在材质上。 */
[data-testid="stChatInput"] {
  background: var(--material-bg) !important;
  backdrop-filter: var(--material-blur);
  -webkit-backdrop-filter: var(--material-blur);
  border-top: 1px solid var(--hairline) !important;
}
[data-testid="stChatInput"] textarea {
  border-radius: 16px !important;
  border: 1px solid var(--border) !important;
  background: var(--surface) !important;
  color: var(--text) !important;           /* 深色主题下聊天输入文字可见 */
  box-shadow: var(--shadow) !important;
  transition: border-color var(--dur-press) var(--ease-out),
              box-shadow var(--dur-press) var(--ease-out) !important;
}
[data-testid="stChatInput"] textarea::placeholder {
  color: var(--text-muted) !important; opacity: 1;
}
[data-testid="stChatInput"] textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px var(--accent-soft), var(--shadow) !important;
}

/* ---------- 弹层 / 折叠面板：随主题，避免深色下突兀的白卡 ----------
   popover / dialog / 下拉选项由 Streamlit 渲染到 body 下的 portal，不在 .stApp 内，
   默认是白底深字；深色主题下虽可读但风格割裂，这里统一用 --surface/--text/--border。
   stExpander 同理（侧边栏“个人信息/参数设置”、主区“复制全文”都用到）。 */
[data-testid="stPopover"], [data-testid="stPopoverBody"],
[data-testid="stDialog"], [data-testid="stDialogBody"],
[data-testid="stSelectboxVirtualDropdown"] {
  background: var(--surface) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"],
[data-testid="stSelectboxVirtualDropdown"] span { color: var(--text) !important; }
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] {
  background: var(--accent-soft) !important;     /* 选中项高亮跟随主题 */
}
[data-testid="stExpander"], [data-testid="stExpanderDetails"] {
  background: var(--surface) !important;
  border-color: var(--border) !important;
}

/* ---------- 助手气泡（st.chat_message） ---------- */
/* 保持实色而非半透明：长对话下每条气泡各开一层 backdrop-filter 会拖慢滚动
   （AUDIT.md：Safari 重 blur 昂贵）。靠顶端高光边 + 软阴影营造材质感，性能更稳。 */
[data-testid="stChatMessage"] {
  background: var(--assistant-bubble-bg) !important;
  border: 1px solid var(--border) !important;
  border-top: 1px solid var(--hairline) !important;
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
  text-decoration: none; color: inherit; cursor: pointer;
}
.cp-msg-row.user .cp-attach-chip { background: rgba(255,255,255,.22); color: var(--user-bubble-fg); }
.cp-attach-chip:hover { opacity: 1; }

/* 附件预览区：图片缩略图 + chip 容器 */
.cp-attaches { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .4rem; align-items: center; }
.cp-attach-img {
  display: block; width: 120px; height: 120px; border-radius: 10px; overflow: hidden;
  border: 1px solid rgba(0,0,0,.12); box-shadow: 0 1px 4px rgba(0,0,0,.12);
  transition: transform var(--dur-press) var(--ease-out), box-shadow var(--dur-press) var(--ease-out); cursor: zoom-in; line-height: 0;
}
.cp-attach-img img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cp-attach-img:hover { transform: scale(1.03); box-shadow: 0 3px 12px rgba(0,0,0,.2); }
.cp-attach-img:active { transform: scale(0.99); }
.cp-msg-row.user .cp-attach-img { border-color: rgba(255,255,255,.35); box-shadow: 0 1px 4px rgba(0,0,0,.25); }

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
/* 流式气泡入场：ease -> 强 ease-out（AUDIT.md：入场用 ease-out） */
[data-testid="stChatMessage"].cp-streaming,
[data-testid="stChatMessage"].cp-thinking-bubble { animation: cp-pop var(--dur-pop) var(--ease-out); }
@keyframes cp-pop { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
/* 停止按钮：胶囊 + 脉冲圆点 */
.cp-stop-btn {
  border-radius: 999px !important; padding: .28rem .9rem !important;
  font-size: .82rem !important; border: 1px solid var(--border) !important;
  background: var(--surface) !important; color: var(--text) !important;
  display: inline-flex !important; align-items: center !important; gap: .4rem !important;
  transition: transform var(--dur-press) var(--ease-out) !important;
}
.cp-stop-btn:active { transform: scale(0.97); }
.cp-stop-btn::before {
  content: ""; width: 8px; height: 8px; border-radius: 50%; background: #e5484d;
  animation: cp-pulse 1.2s infinite ease-in-out;
}
@keyframes cp-pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(229,72,77,.45); } 50% { box-shadow: 0 0 0 5px rgba(229,72,77,0); } }

/* ============ 助手消息操作栏 ============ */
/* 复制全文改用 st.code 原生复制按钮（macOS 可靠），见 app.py 的 st.expander；
   旧的 .cp-act/.cp-actions 自定义 HTML 复制按钮已移除。 */
.cp-meta { font-size: .74rem; color: var(--text-muted); text-align: right; opacity: .85; letter-spacing: 0.01em; }

/* ============ token 用量胶囊 ============ */
.cp-usage { display: flex; flex-wrap: wrap; gap: .4rem; padding: .25rem 0; }
.cp-pill {
  display: inline-flex; align-items: center; gap: .3rem; font-size: .74rem;
  padding: .2rem .6rem; border-radius: 999px; background: var(--accent-soft);
  color: var(--text); border: 1px solid var(--border); letter-spacing: 0.01em;
}
.cp-pill.cp-pill-accent { background: var(--accent); color: #fff; border-color: var(--accent); }
.cp-pill.cp-pill-warn { background: rgba(229,159,0,.14); color: #b58105; border-color: rgba(229,159,0,.3); }

/* ============ 欢迎页 ============ */
/* 空会话首屏：rare/首次频段，是唯一投放 delight 动效预算的地方。
   一次性淡入 + 微上移，强 ease-out；正文/核心输入路径不享受此待遇。 */
.cp-hero {
  text-align: center; padding: 2.4rem 1rem 1.2rem;
  animation: cp-hero-in var(--dur-dock) var(--ease-out) both;
}
@keyframes cp-hero-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
.cp-hero-logo {
  width: 64px; height: 64px; border-radius: 18px; margin: 0 auto .9rem;
  display: flex; align-items: center; justify-content: center; font-size: 2rem;
  background: var(--accent-soft); border: 1px solid var(--border); box-shadow: var(--shadow);
}
.cp-hero h2 { margin: 0 0 .35rem; font-weight: 650; letter-spacing: -0.02em; line-height: 1.08; }
.cp-hero p { margin: 0; opacity: .65; font-size: .92rem; }
/* 灵感卡片：JS 按文本匹配给二级按钮打 cp-sugg-card 类 */
.cp-sugg-card {
  text-align: left !important; height: auto !important; min-height: 60px !important;
  padding: .8rem 1rem !important; border-radius: 14px !important;
  border: 1px solid var(--border) !important; background: var(--surface) !important;
  color: var(--text) !important; white-space: normal !important; line-height: 1.4 !important;
  transition: transform var(--dur-press) var(--ease-out),
              border-color .15s var(--ease-out),
              box-shadow var(--dur-press) var(--ease-out) !important;
}
.cp-sugg-card:hover { transform: translateY(-2px); border-color: var(--accent) !important; box-shadow: var(--shadow) !important; }
.cp-sugg-card:active { transform: scale(0.98); }
.cp-sugg-ic { margin-right: .5rem; }

/* ============ 侧边栏会话项小字 ============ */
.cp-conv-meta { font-size: .7rem; color: var(--text-muted); padding: 0 .15rem .3rem; margin-top: -.2rem; opacity: .8; letter-spacing: 0.01em; }

/* ============ JS 注入用 iframe（components.html, height=0）：确保不占版面 ============ */
[data-testid="stIFrame"] { min-height: 0 !important; line-height: 0; }
[data-testid="stIFrame"] iframe { border: 0; }

/* ============ 编辑框入场（teleporting state -> 过渡） ============
   app.py 用 st.container()+.cp-edit-anchor 标记；occasional 频段，合格。
   只动 transform+opacity（合成友好），高/宽不动画以免触发 layout。 */
section[data-testid="stMain"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"]:has(.cp-edit-anchor) {
  animation: cp-edit-in var(--dur-pop) var(--ease-out) both;
}
@keyframes cp-edit-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

/* ============ 无障碍：三档 reduced 媒体查询（Apple 三信号） ============
   reduced-motion 是「更轻」不是「归零」：保留有助理解的 opacity/颜色，去掉位移与循环。 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
  /* 思考点静态化：保留半隐状态，去掉跳动 */
  .cp-thinking span { animation: none !important; opacity: .5; }
  /* 流式光标静态半隐，不闪 */
  [data-testid="stChatMessage"].cp-streaming .stMarkdown:last-of-type p::after { animation: none !important; opacity: .6; }
  /* 停止按钮脉冲圆点静态 */
  .cp-stop-btn::before { animation: none !important; }
  /* hero / 编辑框入场降为无位移 */
  .cp-hero { animation: none !important; }
}
@media (prefers-reduced-transparency: reduce) {
  /* 材质层转实色，去掉 blur */
  [data-testid="stChatInput"],
  section[data-testid="stMain"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"]:has(.cp-topbar-anchor),
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] [data-testid="stVerticalBlock"]:has(.cp-bottom-anchor) {
    background: var(--surface) !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
  }
}
@media (prefers-contrast: more) {
  :root { --border: rgba(0,0,0,.4); --hairline: rgba(0,0,0,.35); }
  [data-testid="stChatMessage"] { border-width: 2px !important; }
  .stButton > button { border-width: 2px !important; }
}
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
          --material-bg: rgba(19, 25, 34, 0.66);
          --hairline: rgba(255, 255, 255, 0.08);
        }
        .stApp { background: linear-gradient(180deg, #0f1419 0%, #121822 100%); }
        .cp-bubble pre { background: rgba(255,255,255,.08); }
        .cp-attach-chip { background: rgba(255,255,255,.08); }
        /* 代码块：Streamlit 默认套用“浅色”高亮主题（深色字），在深色 --code-bg 上不可读。
           这里自托管一套 GitHub-Dark 风格的 hljs 令牌配色，覆盖到常见 token。 */
        .stCodeBlock pre, .stCodeBlock code { color: #c9d1d9 !important; }
        .stCodeBlock .hljs-comment, .stCodeBlock .hljs-quote { color: #8b949e !important; }
        .stCodeBlock .hljs-keyword, .stCodeBlock .hljs-selector-tag,
        .stCodeBlock .hljs-deletion, .stCodeBlock .hljs-doctag { color: #ff7b72 !important; }
        .stCodeBlock .hljs-string, .stCodeBlock .hljs-regexp,
        .stCodeBlock .hljs-addition, .stCodeBlock .hljs-attribute { color: #a5d6ff !important; }
        .stCodeBlock .hljs-number, .stCodeBlock .hljs-literal,
        .stCodeBlock .hljs-symbol, .stCodeBlock .hljs-bullet { color: #79c0ff !important; }
        .stCodeBlock .hljs-title, .stCodeBlock .hljs-section,
        .stCodeBlock .hljs-name { color: #d2a8ff !important; }
        .stCodeBlock .hljs-type, .stCodeBlock .hljs-built_in,
        .stCodeBlock .hljs-builtin-name { color: #ffa657 !important; }
        .stCodeBlock .hljs-meta, .stCodeBlock .hljs-tag { color: #8b949e !important; }
        .stCodeBlock .hljs-link { color: #a5d6ff !important; }
        /* markdown 内联 code（非 stCodeBlock）：深色主题下给个浅色底+深色字，保持可读 */
        [data-testid="stMarkdownContainer"] code {
          background: rgba(255,255,255,.10) !important;
          color: #e6e8eb !important;
        }
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
