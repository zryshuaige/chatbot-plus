'''配置中心：用 python-dotenv 读取 .env，后端代码绝不硬编码密钥。
所有可配置项集中在这里，其他模块统一从 config 取值。'''
import os
from pathlib import Path
from dotenv import load_dotenv

# step01：定位项目根目录，加载 .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _split_csv(value: str) -> list[str]:
    """把逗号分隔的字符串切成列表，去空去空白。"""
    return [x.strip() for x in (value or "").split(",") if x.strip()]


class Settings:
    """全局配置单例。读取一次，处处复用。"""

    # 大模型相关
    api_key: str = os.getenv("API_KEY", "")
    base_url: str = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")
    default_model: str = os.getenv("DEFAULT_MODEL", "deepseek-ai/DeepSeek-V4-Pro")
    models: list[str] = _split_csv(os.getenv("MODELS", ""))
    utility_model: str = os.getenv("UTILITY_MODEL", "Qwen/Qwen2.5-7B-Instruct")

    # 服务端口
    backend_port: int = int(os.getenv("BACKEND_PORT", "8002"))
    frontend_port: int = int(os.getenv("FRONTEND_PORT", "8502"))

    # 上下文压缩策略
    compress_threshold: int = int(os.getenv("COMPRESS_THRESHOLD", "3000"))
    keep_recent_turns: int = int(os.getenv("KEEP_RECENT_TURNS", "4"))

    # 本地数据目录
    data_dir: Path = BASE_DIR / "data"
    db_path: Path = data_dir / "chatbot.db"
    avatars_dir: Path = data_dir / "avatars"
    files_dir: Path = data_dir / "files"

    # 文件上传
    max_file_size: int = int(os.getenv("MAX_FILE_SIZE_MB", "8")) * 1024 * 1024
    max_file_chars: int = int(os.getenv("MAX_FILE_CHARS", "20000"))

    def ensure_dirs(self) -> None:
        """启动时确保数据目录存在。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.avatars_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
