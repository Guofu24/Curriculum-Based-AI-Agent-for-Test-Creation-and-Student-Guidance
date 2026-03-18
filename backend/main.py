"""
ExamAI Backend - FastAPI Application

Current MVP runtime:
  upload PDF -> parse -> curriculum tree -> scoped retrieval
  -> exam spec -> blueprint -> generate MCQ -> verify -> review/version

Legacy multi-agent modules may still exist on disk for compatibility,
but the active API path is now grounded around the narrow Physics PDF MVP.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db
from routers import (
    auth_router,
    courses_router,
    documents_router,
    exams_router,
    generation_router,
    textbooks_router,
)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup, cleanup on shutdown."""
    logger.info(f"Starting {settings.APP_NAME}...")
    await init_db()
    logger.info("Database tables created.")

    # Pre-load embedding model + Pinecone client at startup
    # This avoids 60+ second delay on the first upload request
    # (sentence-transformers imports torch/tensorflow which is very slow)
    try:
        from services.rag_service import RAGService
        logger.info("Pre-loading RAG service (embedding model + Pinecone)...")
        rag = RAGService.get_instance()
        rag._get_embeddings()    # Force load embedding model now
        rag._get_index()         # Force connect to Pinecone now
        logger.info("RAG service pre-loaded successfully.")
    except Exception as e:
        logger.warning(f"Failed to pre-load RAG service: {e}")
        logger.warning("RAG will be loaded lazily on first request.")

    yield
    logger.info(f"Shutting down {settings.APP_NAME}...")


app = FastAPI(
    title=settings.APP_NAME,
    description="Grounded exam generation MVP for Physics PDFs",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router, prefix=settings.API_PREFIX)
app.include_router(courses_router, prefix=settings.API_PREFIX)
app.include_router(documents_router, prefix=settings.API_PREFIX)
app.include_router(textbooks_router, prefix=settings.API_PREFIX)
app.include_router(exams_router, prefix=settings.API_PREFIX)
app.include_router(generation_router, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
