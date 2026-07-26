# 💬 chatbot-plus

> 一个聚焦「个性化 · 上下文压缩 · 体验增强」的多轮对话聊天机器人，开箱即用，数据全本地。

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white" alt="Streamlit">
  <img src="https://img.shields.io/badge/OpenAI_API-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI API">
  <img src="https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/Pydantic-E92063?style=flat-square&logo=pydantic&logoColor=white" alt="Pydantic">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License">
</p>

---

## ✨ 项目简介

chatbot-plus 是一个基于 LLM 的多轮对话应用，主打**安全、个性、长效记忆与流畅体验**。后端用 FastAPI 提供 SSE 流式接口，前端用 Streamlit 呈现可交互的聊天界面，所有数据落地 SQLite，刷新/重启不丢历史，密钥全程集中管理、零硬编码。

## 🧰 技术栈

### 后端 🛠️
| 技术 | 用途 |
|---|---|
| **FastAPI** + **uvicorn** | 异步 Web 框架与 ASGI 服务器 |
| **LangChain 1.x** | `create_agent` 工具调用编排（ToolMessage / astream_events v2） |
| **LangGraph** | Agent 图运行时（含 `recursion_limit` 防死循环） |
| **ChatOpenAI**（兼容 OpenAI 协议） | 大模型调用（默认走 SiliconFlow） |
| **AsyncOpenAI** | 头像/图片任务走专用画图模型（Z-Image-Turbo / Qwen-Image-Edit） |
| **Pydantic** | 请求/响应数据校验 |
| **python-dotenv** | 配置与密钥加载 |
| **SQLite**（`sqlite3` 标准库） | 会话、消息、用户偏好持久化 |
| **python-pptx / python-docx / openpyxl** | PPT / Word / Excel 文档生成工具 |
| **qrcode** | 二维码生成工具 |
| **python-multipart** | 头像图片上传解析 |

### 前端 🎨
| 技术 | 用途 |
|---|---|
| **Streamlit** | 聊天 UI 主框架（自带 Markdown / 代码块渲染） |
| **requests** | 后端 API 调用 + SSE 流消费封装 |
| **Pillow** | 头像图片处理 |

### 🚪 端口
- 后端 `8002` · 前端 `8502`，均可自由配置。

## 📋 功能清单

| 分类 | 功能 | 说明 |
|---|---|---|
| 🔐 安全 | 密钥集中管理 | 后端零硬编码，密钥不入库，提供配置模板 |
| 👤 个性化 | 头像上传 | 上传图片存本地，气泡内展示，emoji 兜底 |
| 🏷️ 个性化 | 历史自动命名 | 首轮问答后 LLM 生成 ≤12 字标题，可手动改名 |
| 🧭 个性化 | 任务系统提示词 | 日常闲聊/学术研究/代码编程/文案写作/翻译润色/学习辅导，可自定义覆盖 |
| 🖼️ 增强 | 图片生成/编辑（工具） | 专用画图模型（Z-Image-Turbo / Qwen-Image-Edit-2509）通过 `generate_image` / `edit_image` 工具调用 |
| 📝 增强 | **PPT 生成（工具）** | 智能体一键调用 `create_ppt`，内置「商务 / 科技 / 灰度」三主题、六版式（封面/目录/章节/正文/双栏/封底）、页码、配色、字体自动适配中文 |
| 📄 增强 | **Word 文档（工具）** | `create_word_document`：标题分级、目录字段、页码、强调样式 |
| 📊 增强 | **Excel 表格（工具）** | `create_excel_sheet`：表头加粗+配色、首行冻结、列宽自适应 |
| 🌤 增强 | **实时信息工具** | `get_weather`（wttr.in）/ `get_exchange_rate`（open.er-api）/ `get_current_time` / `get_date_info` / `get_ip_info`，全部免 key、TTL 缓存 10 分钟 |
| 🔍 增强 | **GitHub 搜索** | `search_github`：按关键词返回仓库名/stars/语言/简介/链接 |
| 🧮 增强 | **计算器** | `calculate`：白名单 AST 安全求值，避免 `eval` 注入，支持 `+ - * / // % ** ()` 与常量 `pi/e` |
| 🔳 增强 | **二维码** | `generate_qrcode`：把任意文本/链接渲染为 PNG，按链接自动选择附件前缀 |
| 🎨 个性化 | UI 风格切换 | 简约浅色/深色科技/护眼绿/活力紫，CSS 注入即时切换 |
| 🧠 核心 | 上下文压缩 | 超阈值时把旧消息压成摘要，保留最近 N 轮原文，全量历史仍可查看 |
| 🤖 核心 | **LangChain Agent 编排** | `create_agent` 统一调度 13 个工具；非 FC 模型走原 stream_chat，对调用方透明 |
| 🛡️ 核心 | **防「一直思考」死循环** | 三层防护：LangGraph `recursion_limit` + 自研 `LoopGuard` 步数软上限 + 重复调用检测 |
| 👀 体验 | **思考过程可视化** | 前端把 `tool_start` / `tool_limit` / `file` 事件渲染为可折叠步骤卡片，不再像卡死 |
| ✍️ 增强 | Markdown + 代码高亮 + 复制 | 代码块用 `st.code`（自带复制），prose 用 `st.markdown` |
| 🔁 增强 | 重生成 / 编辑 / 停止 | 每条消息可重生成或编辑重发；流式中可停止（保留部分内容） |
| 🤖 增强 | 多模型 + token 用量 | 多模型下拉切换，每次对话显示 prompt/completion/total tokens |
| 🔍 增强 | 会话搜索 + 导出 | 关键词搜标题与内容；单会话导出 Markdown / JSON |
| 📎 增强 | 文件上传 | 文本/代码类文件抽取正文注入上下文；图片等记录文件名；支持随消息发送 |
| 🪵 调优 | **Agent Trace 日志** | `logs/agent.jsonl` 记录每次 run 的 start / tool_start / usage / stop，配套 `AGENT_MAX_STEPS` 调优 |
| 💾 持久化 | 全量落库 | 用户偏好、会话、消息、生成的图片/文档/二维码 文件存 SQLite，刷新/重启不丢 |

## 📁 目录结构

```
chatbot-plus/
├── .gitignore
├── requirements.txt
├── .env.example               # 配置模板（复制为 .env 再填密钥）
├── .venv/                     # uv 创建的虚拟环境（langchain 1.x 要求 Python ≥3.10）
├── run.sh / stop.sh           # 一键启动 / 停止
├── logs/                      # backend.log / frontend.log / agent.jsonl
│
├── backend/
│   ├── main.py                # FastAPI 入口：CORS、头像静态目录、路由注册
│   ├── config.py              # 配置加载 -> Settings（含 AGENT_* / TOOL_CACHE_TTL 等新配置）
│   ├── db.py                  # SQLite 建表 + CRUD
│   ├── llm.py                 # AsyncOpenAI 客户端、token 估算、命名/摘要
│   ├── prompts.py             # 任务 -> 系统提示词库
│   ├── context.py             # 组装 messages + 上下文压缩（导出 LC 消息格式）
│   ├── agent.py               # ✨ LangChain Agent 编排入口
│   ├── logs/agent_trace.py    # ✨ Agent 运行 trace 落盘
│   ├── tools/                 # ✨ Agent 工具集合（13 个）
│   │   ├── attachments.py     # 工具 → 前端附件侧通道（threading.Lock + UUID token）
│   │   ├── info_tools.py      # 天气 / 汇率 / IP / 时间 / 日期
│   │   ├── github_tool.py     # GitHub 仓库搜索
│   │   ├── local_tools.py     # 计算器（白名单 AST）/ 二维码
│   │   ├── image_tools.py     # generate_image / edit_image
│   │   ├── doc_tools.py       # create_ppt / create_word_document / create_excel_sheet
│   │   └── __init__.py        # ALL_TOOLS / get_tools() / TOOL_GROUPS
│   └── routers/
│       ├── chat.py            # POST /chat（SSE 流）+ POST /chat/title
│       │                      # ✨ FC 模型走 agent_stream()，其他模型走原 stream_chat
│       ├── conversations.py   # 增删改查/搜索/导出/截断/追加消息
│       ├── prefs.py           # 偏好读写 + 头像上传
│       └── files.py           # 文件上传 / 下载，文本抽取入库
│
├── frontend/
│   ├── app.py                 # Streamlit 主应用（含 tool-step 步骤渲染）
│   ├── api_client.py          # requests 封装 + SSE 线程消费（可中断）
│   ├── themes.py              # CSS 主题预设（含 .cp-step 步骤样式）
│   └── render.py              # markdown+代码渲染、头像加载
└── data/                      # 运行时生成：chatbot.db + avatars/ + files/（已 gitignore）
```

## 🚀 快速开始

> **依赖说明**：Agent 走的是 LangChain 1.x（`create_agent`），它要求 **Python ≥ 3.10**。建议用 [uv](https://github.com/astral-sh/uv) 创建本地 venv，避免污染全局 Python。

```bash
# 0) 安装 uv（一次即可）
curl -LsSf https://astral.sh/uv/install.sh | sh

cd chatbot-plus

# 1) 创建本地 venv 并安装依赖（首次需要 1-2 分钟，国内源更快）
uv venv -p 3.12 .venv
source .venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 2) 配置密钥：复制 .env.example 为 .env 并填入真实 API_KEY
cp .env.example .env

# 3) 一键启动（后端 + 前端，自动刷新到最新代码）
./run.sh             # 后端 8002 / 前端 8502
#   停止：./stop.sh
#   日志：tail -f logs/backend.log logs/frontend.log
#   Agent 调优：tail -F logs/agent.jsonl | jq .
#   再次运行 ./run.sh 即可热重启刷新
```

或分别手动启动：

```bash
# 后端（终端 A）
source .venv/bin/activate
cd backend && python -m uvicorn main:app --host 127.0.0.1 --port 8002

# 前端（终端 B）
source .venv/bin/activate
cd frontend && streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

浏览器打开 `http://localhost:8502`，左侧「新建对话」选择任务类型或在底部直接输入即开始聊天。💬

> 没有 `.venv` 时 `run.sh` 会回退到系统 `python3`，但 langchain 1.x 需要 3.10+，3.10 以下版本会 `import` 失败。

## 🔧 关键设计

### 🧩 Agent 工具集合（LangChain 1.x `create_agent`）
13 个工具按分组自动注入到位于 `.env` `FC_MODELS` 白名单内的模型：

| 分组 | 工具 | 来源 |
|---|---|---|
| 实时信息（TTL 10min 缓存） | `get_weather` / `get_exchange_rate` / `get_current_time` / `get_date_info` / `get_ip_info` | wttr.in / open.er-api.com / ip-api.com |
| GitHub | `search_github` | api.github.com（免 key，60 次/h） |
| 本地工具 | `calculate`（白名单 AST 安全求值）/ `generate_qrcode` | 本地 |
| 图片 | `generate_image` / `edit_image` | SiliconFlow 文生图 / 图生图专用模型 |
| 文档 | `create_ppt`（3 主题 × 6 版式）/ `create_word_document` / `create_excel_sheet` | python-pptx / python-docx / openpyxl |

工具通过 `tools/attachments.py` 把生成的图片 / 二维码 / 文档推到前端附件侧通道，
绕开 LangChain 把工具返回值强制序列化成字符串的限制。

### 🛑 防「一直思考」死循环（三层防护）
1. **硬上限** — LangGraph `recursion_limit`（`.env` `AGENT_RECURSION_LIMIT`，默认 12）
   触发 `GraphRecursionError` 时由 `agent.py` 捕获并优雅收尾；
2. **软上限** — `LoopGuard.observe_tool_call` 在每次 `on_tool_start` 累计
   工具调用次数，达到 `.env` `AGENT_MAX_STEPS`（默认 6）就主动 `yield` `tool:limit` 事件，
   前端步骤条立刻可见「已达上限」；
3. **重复检测** — 同一 `(tool_name, args)` 出现 ≥ 2 次（`REPEAT_TOLERANCE`），
   判定为模型卡死，发出 `tool:repeat` 事件；下一次模型调用前注入「请基于已有信息直接回答」。

### 🪵 Agent Trace（`logs/agent.jsonl`）
每次 `create_agent.astream_events` 调用的关键事件都会落一行 JSON：
`start / tool_start / tool_limit / usage / stop / error`，共享同一个 `run_id`，
便于复盘「为什么这次跑了 N 个工具 / 为什么被截断」。
`AGENT_TRACE=0` 可关闭以减少 IO。

### 📡 SSE 流式协议
`POST /chat` 返回 `text/event-stream`，事件类型：
`start`（用户消息 id）→ `tool` ×N（步骤可视）→ `token` ×N → `usage` → `done`；异常 `error`；
工具产出文件时穿插 `image` / `file` 事件（含附件元数据）。
前端用独立线程消费，配合 `threading.Event` 实现「停止生成」。

### 🧬 上下文压缩（`context.py`）
- DB 始终保留**全量**历史，前端看到完整对话；
- 发给 LLM 的上下文 = `系统提示 + 摘要 + 最近 N 轮原文 + 当前 query`；
- 估算 token 超阈值且活跃消息足够多时，把较旧消息交给轻量模型生成/追加摘要，更新 `summary_until_msg_id`；
- 摘要持久化，跨会话保留。阈值与保留轮数在「个性化设置」可调。

### 🧩 流式与持久化解耦
助手回复由前端在「完成/停止」时调用 `POST /conversations/{cid}/messages` 落库--这样**停止生成也能保存已产出的部分内容**，而非整段丢弃。

### 🧬 上下文压缩（`context.py`）
- DB 始终保留**全量**历史，前端看到完整对话；
- 发给 LLM 的上下文 = `系统提示 + 摘要 + 最近 N 轮原文 + 当前 query`；
- 估算 token 超阈值且活跃消息足够多时，把较旧消息交给轻量模型生成/追加摘要，更新 `summary_until_msg_id`；
- 摘要持久化，跨会话保留。阈值与保留轮数在「个性化设置」可调。

### 🧩 流式与持久化解耦
助手回复由前端在「完成/停止」时调用 `POST /conversations/{cid}/messages` 落库--这样**停止生成也能保存已产出的部分内容**，而非整段丢弃。

## 🗺️ Roadmap

- 🖼️ **图片视觉理解**：当前图片仅记录文件名，接入视觉模型直接读图
- 🧠 **跨会话长期记忆**：抽取用户画像/偏好写入「记忆库」自动注入系统提示
- 🧩 **提示词变量模板**：`{语言}{篇幅}{语气}` 槽位，任务模板参数化
- 🔁 **重试 + 指数退避**：API 抖动时自动重试，提升稳定性
- 🔌 **可插拔工具注册**：用户可在 `.env` 写自己工具的 Python 类路径，热加载
- 🛡️ **内容安全过滤**：输入/输出敏感内容拦截
- 📊 **用量配额与统计图表**：按天/模型统计 token 与成本（含 `agent.jsonl` 聚合视图）
- 🌿 **对话分支**：从任意消息 fork 出新会话；消息收藏/固定
- 📚 **RAG 知识库**：上传文档切片 + 检索增强回答
- 🎙️ **语音输入/输出**：STT 输入、TTS 朗读回复

## 📝 备注

- token 用量为粗略估算（不依赖 tiktoken），仅用于触发压缩阈值；
- 「停止生成」基于后台线程 + `@st.fragment(run_every=...)` 轮询，响应延迟约 0.3s；
- 单用户本地配置模型，所有数据存本机 `data/`，不联网上报。

---

<p align="center">
  觉得有用就 ⭐ Star 一下叭～
</p>
