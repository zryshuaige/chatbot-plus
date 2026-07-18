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
| **AsyncOpenAI** | 兼容 OpenAI 协议的大模型调用（默认走 SiliconFlow） |
| **Pydantic** | 请求/响应数据校验 |
| **python-dotenv** | 配置与密钥加载 |
| **SQLite**（`sqlite3` 标准库） | 会话、消息、用户偏好持久化 |
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
| 🖼️ 增强 | 图片生成/编辑 | 专用画图模型（Z-Image-Turbo / Qwen-Image-Edit-2509），内置丰富提示词模版；编辑任务上传原图即可改图 |
| 🎨 个性化 | UI 风格切换 | 简约浅色/深色科技/护眼绿/活力紫，CSS 注入即时切换 |
| 🧠 核心 | 上下文压缩 | 超阈值时把旧消息压成摘要，保留最近 N 轮原文，全量历史仍可查看 |
| ✍️ 增强 | Markdown + 代码高亮 + 复制 | 代码块用 `st.code`（自带复制），prose 用 `st.markdown` |
| 🔁 增强 | 重生成 / 编辑 / 停止 | 每条消息可重生成或编辑重发；流式中可停止（保留部分内容） |
| 🤖 增强 | 多模型 + token 用量 | 多模型下拉切换，每次对话显示 prompt/completion/total tokens |
| 🔍 增强 | 会话搜索 + 导出 | 关键词搜标题与内容；单会话导出 Markdown / JSON |
| 📎 增强 | 文件上传 | 文本/代码类文件抽取正文注入上下文；图片等记录文件名；支持随消息发送 |
| 💾 持久化 | 全量落库 | 用户偏好、会话、消息存 SQLite，刷新/重启不丢 |

## 📁 目录结构

```
chatbot-plus/
├── .gitignore
├── requirements.txt
├── README.md
├── backend/
│   ├── main.py                # FastAPI 入口：CORS、头像静态目录、路由注册
│   ├── config.py              # 配置加载 -> Settings
│   ├── db.py                  # SQLite 建表 + CRUD
│   ├── llm.py                 # AsyncOpenAI 客户端、token 估算、命名/摘要
│   ├── prompts.py             # 任务 -> 系统提示词库
│   ├── context.py             # 组装 messages + 上下文压缩
│   └── routers/
│       ├── chat.py            # POST /chat（SSE 流）+ POST /chat/title
│       ├── conversations.py   # 增删改查/搜索/导出/截断/追加消息
│       ├── prefs.py           # 偏好读写 + 头像上传
│       └── files.py           # 文件上传 / 下载，文本抽取入库
├── frontend/
│   ├── app.py                 # Streamlit 主应用
│   ├── api_client.py          # requests 封装 + SSE 线程消费（可中断）
│   ├── themes.py              # CSS 主题预设
│   └── render.py              # markdown+代码渲染、头像加载
└── data/                      # 运行时生成：chatbot.db + avatars/（已 gitignore）
```

## 🚀 快速开始

```bash
cd chatbot-plus
pip install -r requirements.txt

# 1) 配置密钥：按仓库内的配置模板填入自己的 API Key

# 2) 一键启动（后端 + 前端，自动刷新到最新代码）
./run.sh
#   停止：./stop.sh   日志：tail -f logs/backend.log logs/frontend.log
#   再次运行 ./run.sh 即可重启刷新
```

或分别手动启动：

```bash
# 后端（终端 A）
cd backend && python3 main.py
# 前端（终端 B）
cd frontend && streamlit run app.py --server.port 8502
```

浏览器打开 `http://localhost:8502`，左侧「新建对话」选择任务类型或在底部直接输入即开始聊天。💬

## 🔧 关键设计

### 📡 SSE 流式协议
`POST /chat` 返回 `text/event-stream`，事件类型：`start`（回传用户消息 id）-> `token` ×N -> `usage`（token 用量 + 是否压缩）-> `done`；异常发 `error`。前端用独立线程消费，配合 `threading.Event` 实现「停止生成」。

### 🧬 上下文压缩（`context.py`）
- DB 始终保留**全量**历史，前端看到完整对话；
- 发给 LLM 的上下文 = `系统提示 + 摘要 + 最近 N 轮原文 + 当前 query`；
- 估算 token 超阈值且活跃消息足够多时，把较旧消息交给轻量模型生成/追加摘要，更新 `summary_until_msg_id`；
- 摘要持久化，跨会话保留。阈值与保留轮数在「个性化设置」可调。

### 🧩 流式与持久化解耦
助手回复由前端在「完成/停止」时调用 `POST /conversations/{cid}/messages` 落库--这样**停止生成也能保存已产出的部分内容**，而非整段丢弃。

### 🛡️ 工程化要点
- 密钥硬编码 -> 集中配置管理
- 全局共享 `messages`（线程不安全）-> 每请求独立组装
- 刷新丢历史 -> SQLite 持久化
- 文件上传未落地 -> 头像真正存储展示
- 上下文粗暴截断 -> 摘要压缩

## 🗺️ Roadmap

- 🖼️ **图片视觉理解**：当前图片仅记录文件名，接入视觉模型直接读图
- 🧠 **跨会话长期记忆**：抽取用户画像/偏好写入「记忆库」自动注入系统提示
- 🧩 **提示词变量模板**：`{语言}{篇幅}{语气}` 槽位，任务模板参数化
- 🔁 **重试 + 指数退避**：API 抖动时自动重试，提升稳定性
- 🛡️ **内容安全过滤**：输入/输出敏感内容拦截
- 📊 **用量配额与统计图表**：按天/模型统计 token 与成本
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
