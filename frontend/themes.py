'''UI 风格预设：通过注入 CSS 实现“浅色/深色/护眼/活力”四套主题。
Streamlit 运行时不支持改 light/dark 基色，所以用 CSS 覆盖关键元素。'''

THEMES = {
    "minimal": {
        "name": "简约浅色",
        "css": """
        <style>
        .stApp { background: #fafafa; }
        [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #eee; }
        .stChatMessage { border-radius: 12px; }
        </style>
        """,
    },
    "dark": {
        "name": "深色科技",
        "css": """
        <style>
        .stApp { background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%); color: #e2e8f0; }
        [data-testid="stSidebar"] { background: #0b1220; border-right: 1px solid #1e293b; }
        .stChatMessage { background: #1e293b; border: 1px solid #334155; border-radius: 12px; }
        .stMarkdown, .stText { color: #e2e8f0; }
        section[data-testid="stSidebar"] * { color: #cbd5e1; }
        </style>
        """,
    },
    "green": {
        "name": "护眼绿",
        "css": """
        <style>
        .stApp { background: #f1f5ec; }
        [data-testid="stSidebar"] { background: #e6eedd; border-right: 1px solid #cdd9b8; }
        .stChatMessage { border-radius: 12px; border: 1px solid #cdd9b8; }
        </style>
        """,
    },
    "purple": {
        "name": "活力紫",
        "css": """
        <style>
        .stApp { background: linear-gradient(180deg, #faf5ff 0%, #f3e8ff 100%); }
        [data-testid="stSidebar"] { background: #f5f0ff; border-right: 1px solid #e9d5ff; }
        .stChatMessage { border-radius: 12px; border: 1px solid #e9d5ff; }
        </style>
        """,
    },
}

DEFAULT_THEME = "minimal"


def theme_keys() -> list[str]:
    return list(THEMES.keys())


def theme_name(key: str) -> str:
    return THEMES.get(key, THEMES[DEFAULT_THEME])["name"]


def theme_css(key: str) -> str:
    return THEMES.get(key, THEMES[DEFAULT_THEME])["css"]
