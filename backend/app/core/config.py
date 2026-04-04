"""Configuration management using Pydantic Settings."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/curriculum_ai"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # LLM Provider
    LLM_PROVIDER: str = "groq"
    LLM_FALLBACK_CHAIN: str = "groq,g4f"

    @property
    def fallback_providers(self) -> list[str]:
        """Parse fallback chain from comma-separated string."""
        if not self.LLM_FALLBACK_CHAIN:
            return []
        return [p.strip() for p in self.LLM_FALLBACK_CHAIN.split(",") if p.strip()]

    # Model routing
    LLM_MODEL_STRONG: str = "llama-3.3-70b-versatile"
    LLM_MODEL_LIGHT: str = "llama-3.1-8b-instant"
    LLM_MODEL_VISION: str = "llama-3.2-11b-vision-preview"

    # Provider API keys
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_APP_NAME: str = "curriculum-ai-agent"
    GROQ_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # Ollama
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL_STRONG: str = "llama3.2"
    OLLAMA_MODEL_LIGHT: str = "llama3.2"

    # Local sentence-transformers embedding (replaces OpenAI)
    ST_EMBEDDING_MODEL: str = "paraphrase-multilingual-mpnet-base-v2"
    ST_EMBEDDING_DIM: int = 768

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX: str = "curriculum-ai"
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"

    # Storage backend: "minio" (default, local) | "s3" (AWS)
    STORAGE_BACKEND: str = "minio"

    # MinIO — local S3-compatible storage (priority default)
    MINIO_ENDPOINT_URL: str = "http://127.0.0.1:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET_NAME: str = "curriculum-ai"
    # Public URL returned inside presigned links (same as endpoint for local dev)
    MINIO_PUBLIC_URL: str = "http://127.0.0.1:9000"

    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-southeast-1"
    S3_BUCKET_NAME: str = "curriculum-ai-uploads"
    S3_PRESIGNED_URL_TTL: int = 3600

    # MathPix (formula OCR — optional fallback)
    MATHPIX_APP_ID: str = ""
    MATHPIX_APP_KEY: str = ""

    # Qwen Vision (primary OCR + image description — self-hosted on Kaggle/ngrok)
    # Set to the ngrok public URL, e.g. https://xxxx.ngrok-free.app
    QWEN_VISION_BASE_URL: str = ""
    # Timeout in seconds — keep high, model runs partially on CPU via ngrok
    QWEN_VISION_TIMEOUT: float = 120.0

    # LangFuse (Observability)
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_ENABLED: bool = True

    # JWT
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False
    DEMO_MODE: bool = False

    # App base URL — used for constructing WebSocket URLs returned to frontend clients
    APP_BASE_URL: str = "http://localhost:8000"

    @property
    def ws_base_url(self) -> str:
        """WebSocket base URL derived from APP_BASE_URL (http→ws, https→wss)."""
        return self.APP_BASE_URL.replace("http://", "ws://").replace("https://", "wss://")

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Agent settings
    AGENT_MAX_RETRIES: int = 3
    AGENT_TIMEOUT_RETRIEVAL: int = 30
    AGENT_TIMEOUT_OUTLINE: int = 20
    AGENT_TIMEOUT_BUILDER: int = 120
    AGENT_TIMEOUT_VALIDATOR: int = 60
    AGENT_TIMEOUT_PLANNER: int = 15
    AGENT_MAX_VALIDATION_RETRIES: int = 3
    AGENT_TOKEN_BUDGET: int = 50000
    AGENT_MAX_WEB_SEARCH_CALLS: int = 10

    # RAG settings
    RAG_TOP_K_PER_CHAPTER: int = 20
    RAG_TOP_K_AFTER_RERANK: int = 8
    RAG_CHUNK_SIZE: int = 1200
    RAG_CHUNK_OVERLAP: int = 200
    EMBEDDING_CACHE_TTL_SECONDS: int = 604800  # 7 days

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _coerce_debug(cls, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
