"""
VibeRAG 配置管理
"""
import os
import platform
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""

    # 应用信息
    APP_NAME: str = "VibeRAG"
    APP_VERSION: str = "0.21"

    # 数据目录（跨平台）
    def get_data_dir() -> Path:
        if platform.system() == "Darwin":
            return Path.home() / "Library" / "Application Support" / "VibeRAG"
        elif platform.system() == "Windows":
            return Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "VibeRAG"
        else:
            return Path.home() / ".vibrag"

    DATA_DIR: Path = get_data_dir()

    # 数据库
    DATABASE_PATH: Path = DATA_DIR / "library.db"

    # Ollama 配置
    OLLAMA_HOST: str = "http://localhost:11434"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSION: int = 768

    # 向量检索配置
    TOP_K: int = 5
    SIMILARITY_THRESHOLD: float = 0.35

    # 分块配置
    CHUNK_SIZE: int = 600  # tokens
    CHUNK_OVERLAP: int = 100  # tokens

    # LLM 配置
    LLM_PROVIDER: str = "openai"  # openai / anthropic / custom
    LLM_API_BASE_URL: Optional[str] = None  # 自定义 API 地址
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "gpt-4o-mini"

    # 安全配置
    PASSWORD_HASH: Optional[str] = None
    AUTO_LOCK_MINUTES: int = 3

    # 上传文件大小限制（MB）
    MAX_FILE_SIZE: int = 50

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()

# 确保数据目录存在
settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
