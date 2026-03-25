import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings
from typing import Optional

_BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    # App
    APP_NAME: str = "ExamAI"
    APP_ENV: str = "development"
    DEBUG: bool = True
    SECRET_KEY: str = "change-this-to-a-secure-random-string"
    API_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://examai:examai@localhost:5432/examai"

    # LLM
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    G4F_MODEL: str = "gpt-4o"
    G4F_PROVIDER: str = "Blackbox"
    TOGETHER_API_KEY: Optional[str] = None
    TOGETHER_MODEL: str = "deepcogito/cogito-v1-preview-qwen-32B"
    GOOGLE_API_KEY: Optional[str] = None
    GOOGLE_MODEL: str = "gemini-2.0-flash"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # Embedding
    # Keep model/dimension aligned by default (MiniLM = 384 dims).
    EMBEDDING_PROVIDER: str = "huggingface"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    EMBEDDING_ALLOW_FALLBACK: bool = True
    EMBEDDING_DISABLE_VECTOR_INDEX_WHEN_FALLBACK: bool = True
    VECTOR_SEARCH_TIMEOUT_SECONDS: float = 6.0

    # Pinecone (free cloud vector DB)
    PINECONE_API_KEY: Optional[str] = None
    PINECONE_INDEX_NAME: str = "examai"
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"

    # Rate limiting — LLM API (Groq free tier: 12K TPM)
    LLM_REQUEST_DELAY: float = 6.0  # Seconds between LLM calls
    MAX_CHUNK_CHARS: int = 1200      # Max chars per chunk sent to LLM

    # File Storage
    UPLOAD_DIR: str = str(_BASE_DIR / "data" / "uploads")
    MAX_UPLOAD_SIZE_MB: int = 100

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://192.168.78.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ]

    # Auth — JWT tokens
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15              # Short-lived access token (15 phút)
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7                 # Long-lived refresh token (7 ngày)
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24    # Email verification link TTL
    ALGORITHM: str = "HS256"

    # Rate limiting — chống brute-force login
    LOGIN_RATE_LIMIT_REQUESTS: int = 5                 # Số request tối đa
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60          # Trong khoảng thời gian (giây)

    # SMTP (stub — log ra console nếu chưa cấu hình)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: str = "noreply@examai.local"
    PLAYBOOK_RETRIEVAL_MODE: str = "off"
    PLAYBOOK_RETRIEVAL_LIMIT: int = 3

    @field_validator("DEBUG", mode="before")
    @classmethod
    def normalize_debug_flag(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "production"}:
                return False
        return value

    @field_validator("PLAYBOOK_RETRIEVAL_MODE", mode="before")
    @classmethod
    def normalize_playbook_mode(cls, value):
        normalized = str(value or "off").strip().lower()
        if normalized not in {"off", "shadow", "limited"}:
            return "off"
        return normalized

    model_config = {"env_file": str(_BASE_DIR / ".env"), "extra": "ignore"}


settings = Settings()
