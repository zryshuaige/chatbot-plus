'''FastAPI 应用入口：注册路由、挂载头像静态目录、开启 CORS。
启动：python main.py  或  uvicorn main:app --reload --port 8002'''
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import db
from config import settings
from routers import chat, conversations, prefs

# step01：建库建表
db.init_db()

app = FastAPI(title="chatbot-plus 后端")

# step02：CORS（允许 Streamlit 前端跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# step03：挂载头像静态目录 -> /avatars/xxx.png
app.mount("/avatars", StaticFiles(directory=str(settings.avatars_dir)), name="avatars")

# step04：注册路由
app.include_router(chat.router, tags=["chat"])
app.include_router(conversations.router, tags=["conversations"])
app.include_router(prefs.router, tags=["prefs"])


@app.get("/")
async def root():
    return {"code": 200, "message": "chatbot-plus 后端已就绪，前端请访问 Streamlit。"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=settings.backend_port)
