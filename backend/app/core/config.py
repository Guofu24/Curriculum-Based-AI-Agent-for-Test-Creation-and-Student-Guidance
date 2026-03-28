"""Configuration management using Pydantic Settings."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/curriculum_ai"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL_ORCHESTRATOR: str = "gpt-4o"
    OPENAI_MODEL_BUILDER: str = "gpt-4o"
    OPENAI_MODEL_VALIDATOR: str = "gpt-4o"
    OPENAI_MODEL_PLANNER: str = "gpt-4o-mini"
    OPENAI_MODEL_RERANKER: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    OPENAI_EMBEDDING_DIM: int = 3072

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX: str = "curriculum-ai"
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"

    # AWS S3
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "ap-southeast-1"
    S3_BUCKET_NAME: str = "curriculum-ai-uploads"
    S3_PRESIGNED_URL_TTL: int = 3600

    # MathPix (formula OCR)
    MATHPIX_APP_ID: str = ""
    MATHPIX_APP_KEY: str = ""

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

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
