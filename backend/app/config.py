import secrets
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # OpenAI
    OPENAI_API_KEY: str = ""

    # Qdrant — local (host:port) or cloud (URL)
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_URL: str = ""         # e.g. https://xxx.us-east4-0.gcp.cloud.qdrant.io:6333
    QDRANT_API_KEY: str = ""

    # Model Configuration
    EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_DIMENSIONS: int = 3072
    LLM_MODEL: str = "gpt-4o"
    TEMPERATURE: float = 0.1

    # RAG Configuration
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    TOP_K: int = 5

    # App
    APP_NAME: str = "JadwaChat"
    APP_VERSION: str = "2.0.0"
    DATABASE_URL: str = "sqlite+aiosqlite:///./jadwachat.db"

    # JWT Authentication
    JWT_SECRET_KEY: str = secrets.token_urlsafe(32)  # auto-generated if not set
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Security
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,https://frontend1-production-13ce.up.railway.app,https://jadwa-chat.com,https://www.jadwa-chat.com"
    MAX_UPLOAD_SIZE_MB: int = 50
    RATE_LIMIT_CHAT: str = "30/minute"
    RATE_LIMIT_UPLOAD: str = "10/minute"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
