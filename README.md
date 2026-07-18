# chatbot-plus

在 **project-a**（FastAPI + Streamlit 多轮聊天机器人）基础上升级的独立项目，沿用同一技术栈，**不修改 project-a**。聚焦“密钥安全 + 个性化 + 上下文压缩 + 体验增强”。

## 技术栈（与 project-a 一致 + 标准库）

- 后端：FastAPI + uvicorn + AsyncOpenAI（SiliconFlow）+ python-dotenv + Pydantic + SQLite（`sqlite3` 标准库）
- 前端：Streamlit + requests + Pillow（Streamlit 自带依赖）
- 端口：后端 `8002` / 前端 `8502`（避开 project-a 的 `8001`），均可 `.env` 配置

## 功能清单

| 分类 | 功能 | 说明 |
|---|---|---|
| 安全 | 密钥 `.env` 化 | 后端零硬编码，`.env` 不入库，`.env.example` 为模板 |
| 个性化 | 头像上传 | 上传图片存本地，气泡内展示，emoji 兜底 |
| 个性化 | 历史自动命名 | 首轮问答后 LLM 生成 ≤12 字标题，可手动改名 |
| 个性化 | 任务系统提示词 | 日常闲聊/学术研究/代码编程/文案写作/翻译润色/学习辅导，可自定义覆盖 |
| 个性化 | UI 风格切换 | 简约浅色/深色科技/护眼绿/活力紫，CSS 注入即时切换 |
| 核心 | 上下文压缩 | 超阈值时把旧消息压成摘要，保留最近 N 轮原文，全量历史仍可查看 |
| 增强 | Markdown+代码高亮+复制 | 代码块用 `st.code`（自带复制），prose 用 `st.markdown` |
| 增强 | 重生成 / 编辑 / 停止 | 每条消息可重生成或编辑重发；流式中可停止（保留部分内容） |
| 增强 | 多模型 + token 用量 | `.env` 配置多模型下拉，每次对话显示 prompt/completion/total tokens |
| 增强 | 会话搜索 + 导出 | 关键词搜标题与内容；单会话导出 Markdown / JSON |
| 持久化 | 全量落库 | 用户偏好、会话、消息存 SQLite，刷新/重启不丢 |

## 目录结构

```
chatbot-plus/
├── .env / .env.example        # 真实配置 / 模板（密钥、端口、模型、压缩阈值）
├── .gitignore
├── requirements.txt
├── README.md
├── backend/
│   ├── main.py                # FastAPI 入口：CORS、头像静态目录、路由注册
│   ├── config.py              # dotenv 加载 -> Settings
│   ├── db.py                  # SQLite 建表 + CRUD
│   ├── llm.py                 # AsyncOpenAI 客户端、token 估算、命名/摘要
│   ├── prompts.py             # 任务 -> 系统提示词库
│   ├── context.py             # 组装 messages + 上下文压缩
│   └── routers/
│       ├── chat.py            # POST /chat（SSE 流）+ POST /chat/title
│       ├── conversations.py   # 增删改查/搜索/导出/截断/追加消息
│       └── prefs.py           # 偏好读写 + 头像上传
├── frontend/
│   ├── app.py                 # Streamlit 主应用
│   ├── api_client.py          # requests 封装 + SSE 线程消费（可中断）
│   ├── themes.py              # CSS 主题预设
│   └── render.py              # markdown+代码渲染、头像加载
└── data/                      # 运行时生成：chatbot.db + avatars/（已 gitignore）
```

## 快速开始

```bash
cd chatbot-plus
pip install -r requirements.txt

# 1) 配置密钥（仓库已带一份可用的 .env；换自己的 key 就改这里）
cp .env.example .env      # 然后编辑 .env 填入 API_KEY

# 2) 启动后端（终端 A）
cd backend
python3 main.py
#   或：uvicorn main:app --reload --port 8002

# 3) 启动前端（终端 B）
cd frontend
streamlit run app.py --server.port 8502
```

浏览器打开 `http://localhost:8502`，左侧「新建对话」或在底部直接输入即开始聊天。

## 关键设计

### SSE 流式协议
`POST /chat` 返回 `text/event-stream`，事件类型：`start`（回传用户消息 id）→ `token` ×N → `usage`（token 用量 + 是否压缩）→ `done`；异常发 `error`。前端用独立线程消费，配合 `threading.Event` 实现“停止生成”。

### 上下文压缩（`context.py`）
- DB 始终保留**全量**历史，前端看到完整对话；
- 发给 LLM 的上下文 = `系统提示 + 摘要 + 最近 N 轮原文 + 当前 query`；
- 估算 token 超阈值且活跃消息足够多时，把较旧消息交给轻量模型生成/追加摘要，更新 `summary_until_msg_id`；
- 摘要持久化，跨会话保留。阈值与保留轮数在「个人化设置」可调。

### 流式与持久化解耦
助手回复由前端在“完成/停止”时调用 `POST /conversations/{cid}/messages` 落库——这样**停止生成也能保存已产出的部分内容**，而非整段丢弃。

### 修复的 project-a 缺陷
- 密钥硬编码 → `.env`
- 全局共享 `messages`（线程不安全）→ 每请求独立组装
- 刷新丢历史 → SQLite 持久化
- 文件上传未落地 → 头像真正存储展示
- 上下文粗暴截断 → 摘要压缩

## Roadmap（建议的后续建设性方向）

- **多模态文件处理**：上传 CSV 走 pandas 分析、图片走视觉模型（前端已留 `file_uploader` 经验）
- **跨会话长期记忆**：抽取用户画像/偏好写入“记忆库”自动注入系统提示
- **提示词变量模板**：`{语言}{篇幅}{语气}` 槽位，任务模板参数化
- **重试 + 指数退避**：API 抖动时自动重试，提升稳定性
- **内容安全过滤**：输入/输出敏感内容拦截
- **用量配额与统计图表**：按天/模型统计 token 与成本
- **对话分支**：从任意消息 fork 出新会话；消息收藏/固定
- **RAG 知识库**：上传文档切片+检索增强回答
- **语音输入/输出**：STT 输入、TTS 朗读回复

## 备注

- token 用量为粗略估算（不依赖 tiktoken），仅用于触发压缩阈值；
- “停止生成”基于后台线程 + `@st.fragment(run_every=...)` 轮询，响应延迟约 0.3s；
- 单用户本地配置模型，所有数据存本机 `data/`，不联网上报。
