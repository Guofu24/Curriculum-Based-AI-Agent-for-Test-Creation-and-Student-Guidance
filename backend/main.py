"""
ExamAI Backend — FastAPI Application

Multi-Agent AI system for automated exam generation from textbooks.

Architecture:
  FastAPI ─→ ExamService ─→ LangGraph Orchestrator
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
              BlueprintAgent  RetrievalAgent  QuestionGenerator
                                    │               │
                              ChromaDB (RAG)   ValidatorAgent
                                                    │
                                              ReviewerAgent
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import init_db
from routers import auth_router, textbooks_router, exams_router, generation_router

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
    yield
    logger.info(f"Shutting down {settings.APP_NAME}...")


app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-Agent AI system for automated exam generation from textbooks",
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
