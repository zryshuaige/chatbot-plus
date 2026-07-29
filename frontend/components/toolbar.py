"""工具栏（输入区上方的 chip 行）。

设计要点：
- 5 个 chip 永远占位（即便后端没拉到元数据），单 chip 失败 → 该 chip 标灰禁用，其它正常工作。
- CSS-only 钉底（在 themes.py 配 .cp-toolbar position: sticky; bottom: 0）：不依赖 JS 测量 /
  MutationObserver / setInterval，完全避免主进程依赖。
- @st.fragment 隔离：点 chip 只 fragment 内部 rerun，不会清空 chat_input 已输入的文字。
"""
import streamlit as st
import api_client as api


# 5 个固定 chip 顺序与默认标签：从未拉到元数据也按这个顺序渲染占位（保持视觉稳定）
CHIP_LAYOUT = [
    ("info",   "🌤  实时"),
    ("local",  "🧮  计算"),
    ("image",  "🎨  图片"),
    ("doc",    "📄  文档"),
    ("github", "🐙 GitHub"),
]


def _fetch_groups() -> dict:
    """获取工具分组元数据。返回 key->group dict；失败返回 {}（所有 chip 渲染为 disabled）。"""
    try:
        groups = api.get_tool_groups()
        if not isinstance(groups, list):
            return {}
        return {g.get("key"): g for g in groups if g.get("key")}
    except Exception as e:
        print(f"[toolbar] get_tool_groups failed: {e}")
        return {}


@st.fragment
def chips_panel():
    """5 chip 工具栏。永远渲染；单 chip 失败只禁用该 chip。

    视觉降级：
    - 默认 5 chip 占位，opacity .55（浅灰），cursor not-allowed
    - 拉到元数据 → opacity 1，cursor pointer
    - 用户选中（点亮的 primary 颜色）→ 即便元数据失败也禁用，避免选了一个没 tool 的组

    图片任务下：所有 chip disabled，上方加一行 caption 提醒用户切回文本任务可启用。
    """
    # 后端兼容性：图片任务下要让用户看到「已切图片任务；工具不可用」
    is_image_task = False
    try:
        from app import _is_image_task  # type: ignore
        is_image_task = _is_image_task()
    except Exception:
        pass

    groups = _fetch_groups()

    # 图片任务下：显示一行 caption，但仍渲染 5 chip 占位（位置不动），
    # 这样切回文本任务时 chip 不会"跳一下"
    if is_image_task:
        st.markdown(
            "<div class='cp-toolbar-caption'>🎨 图片任务已选定 · "
            "工具栏已禁用，切回文本任务可启用</div>",
            unsafe_allow_html=True,
        )

    # 占位渲染（即使 groups 为空，5 个 chip 也会出现）
    sel = st.session_state.get("_selected_tool")
    cols = st.columns(len(CHIP_LAYOUT), gap="small")
    for i, (key, label) in enumerate(CHIP_LAYOUT):
        g = groups.get(key)
        ready = bool(g and g.get("ready", len(g.get("tools", []) or []) > 0))
        disabled = (not ready) or is_image_task
        is_sel = (sel == key) and ready

        # hint 文案：拉到 hint 显示 hint，否则显示通用提示
        help_txt = (g.get("hint") if g else None) or "未就绪：后端工具尚未加载"
        if is_image_task:
            help_txt = "图片任务下工具已禁用"

        # 计算 CSS class（外层 div 用 className 加状态）
        cls_parts = ["cp-chip"]
        if ready and not is_image_task:
            cls_parts.append("is-ready")
        else:
            cls_parts.append("is-disabled")
        if is_sel:
            cls_parts.append("is-selected")
        cls_str = " ".join(cls_parts)

        # 用一段自定义 HTML 包装原生 button：保留 Streamlit 原生 widget 行为（点击状态、disabled），同时支持 CSS className
        # 关键：必须用 st.button 触发 session_state 更新，不用纯 HTML button
        # 这里用 st.markdown 渲染一个 wrapper div，但里面的 button 不能跨 fragment 走 Streamlit widget
        # 折中：直接把 className 加到 st.container(key=...) 上的 div 通过 CSS 选择器来匹配（靠 :nth-child）
        # 最稳的方案：仍用 st.button，仅在按下后由 fragment 设置 class 状态
        if cols[i].button(
            label,
            key=f"tool_chip_{key}",
            help=help_txt,
            disabled=disabled,
            type="primary" if is_sel else "secondary",
            use_container_width=True,
        ):
            # 切换选中
            st.session_state["_selected_tool"] = None if is_sel else key
            st.session_state["_chip_active"] = key
            # 用 session_state 标记本 chip 当前激活 class（CSS 用 :has 命中）
            st.session_state[f"_chip_state_{key}"] = "selected" if not is_sel else "idle"


def get_selected_tool_placeholder(selected: str | None) -> str | None:
    """根据选中的工具返回 chat_input 的 placeholder 文本。未选中返回 None。"""
    if not selected:
        return None
    placeholders = {
        "info":   "已选「实时信息」· 输入如：北京今天天气、100 美元换多少人民币…",
        "github": "已选「GitHub 搜索」· 输入要找的开源库关键词…",
        "local":  "已选「数学计算」· 输入算式如：(3.14*12**2)/2 …",
        "image":  "已选「图片生成」· 输入画面描述（主体+环境+光线+风格）…",
        "doc":    "已选「文档生成」· 输入主题与要求，如：5 页关于 AI 的 PPT…",
    }
    return placeholders.get(selected)
