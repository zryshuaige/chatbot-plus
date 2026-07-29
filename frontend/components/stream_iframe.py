"""把 stream_bubble.html 包装成可注入参数的 HTML 字符串。

使用方式：
    from components.stream_iframe import render_stream_iframe
    render_stream_iframe(height=600, params={"cid": ..., "query": ...})

iframe 内 JS 读取 window.STREAM_PARAMS 自动开始 POST /chat 并渲染流式响应。
"""
from pathlib import Path

HTML_PATH = Path(__file__).with_name("stream_bubble.html")


def render_stream_iframe(height: int = 600, params: dict | None = None) -> str:
    """读取 HTML 文件并注入参数；返回完整 HTML 字符串给 components.html。

    params 结构：
        - cid: str                  会话 id
        - query: str                用户消息
        - regenerate: bool          是否重新生成（不带新 user 消息）
        - temperature/top_p/max_tokens: 采样参数
        - file_ids: list[str]       已上传的附件 id
        - backend_url: str          后端 base URL（默认从 window.parent 推断）
        - on_done: bool             是否在完成时通知父页面
    """
    base = HTML_PATH.read_text(encoding="utf-8")
    import json
    # 把 params 注入到一段内联 script（在主脚本前执行）
    inject = (
        "<script>window.STREAM_PARAMS = "
        + json.dumps(params or {}, ensure_ascii=False)
        + ";</script>"
    )
    # 插到 </head> 之前
    return base.replace("</head>", inject + "</head>", 1)