"""FastAPI main application."""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import logging

from app.core.config import get_settings
from app.core.database import init_db, close_db
from app.core.redis_client import close_redis
from app.routers.auth import router as auth_router
from app.routers.courses import router as courses_router
from app.routers.documents import router as documents_router
from app.routers.exams import router as exams_router
from app.routers.generate import router as generate_router
from app.routers.playbook import router as playbook_router

settings = get_settings()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan event handler for startup and shutdown.
    Handles: DB init, Redis setup, background tasks.
    """
    # Startup
    logger.info("Starting Curriculum AI Backend...")

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")

    # Test Redis connection
    try:
        from app.core.redis_client import get_redis_client
        redis = get_redis_client()
        await redis.client.ping()
        logger.info("Redis connected")
    except Exception as e:
        logger.warning(f"Redis connection skipped: {e}")

    yield

    # Shutdown
    logger.info("Shutting down...")
    # Close all WebSocket listeners before shutting down Redis
    manager = get_connection_manager()
    await manager.shutdown()
    await close_db()
    await close_redis()
    logger.info("Cleanup complete")


# Create FastAPI app
app = FastAPI(
    title="Curriculum AI Agent API",
    description="Multi-agent AI system for automatic test paper generation from teaching materials",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ── Middleware ────────────────────────────────────────────────────────────────

# CORS
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip compression
app.add_middleware(GZipMiddleware, minimum_size=1000)


# ── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Liveness probe — basic health check.
    Returns status 'healthy' when the service is running.
    For full service readiness (postgres + redis + pinecone), use /ready instead.
    """
    return {
        "status": "healthy",
        "version": "2.0.0",
        "service": "curriculum-ai-agent",
    }


@app.get(
    "/ready",
    tags=["Health"],
    summary="Readiness check — verify all dependencies",
    description="Deep health check that verifies connectivity to all external services: "
                 "PostgreSQL (database), Redis (caching/pubsub), and Pinecone (vector store). "
                 "Use this as a Kubernetes readiness probe. "
                 "Returns `ready: true` only when ALL services respond 'ok'. "
                 "Individual service status is returned in the `checks` object.",
    responses={
        200: {"description": "Service readiness status with per-service checks"},
        503: {"description": "Service unavailable — one or more dependencies down"},
    },
)
async def readiness_check():
    """Readiness check endpoint."""
    checks = {}

    # Database check
    try:
        from sqlalchemy import text
        from app.core.database import async_session_maker
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Redis check
    try:
        from app.core.redis_client import get_redis_client
        redis = get_redis_client()
        await redis.client.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    # Pinecone check
    try:
        from app.rag.vector_store import get_vector_store
        store = get_vector_store()
        stats = await store.describe_index_stats()
        checks["pinecone"] = "ok" if stats else "unavailable"
    except Exception as e:
        checks["pinecone"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())

    return {
        "ready": all_ok,
        "checks": checks,
    }


# ── API Routers ──────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(courses_router)
app.include_router(documents_router)
app.include_router(exams_router)
app.include_router(generate_router)
app.include_router(playbook_router)


# ── WebSocket Endpoint ─────────────────────────────────────────────────────────

from fastapi import WebSocket
from app.websocket.manager import get_connection_manager


@app.websocket("/ws/exam/{exam_id}")
async def websocket_exam_stream(websocket: WebSocket, exam_id: str):
    """
    WebSocket endpoint for real-time exam generation streaming.
    Clients connect to receive live generation progress events.

    Flow:
    1. connect() → accept + replay stored events from Redis (G19)
    2. listen_redis() → subscribe to Redis channel exam:{exam_id} and forward
       all events to the client
    3. On disconnect → ConnectionManager.disconnect() cleans up the connection
    """
    manager = get_connection_manager()
    await manager.connect(websocket, exam_id)

    try:
        # G19: Subscribe to Redis channel exam:{exam_id} and forward events
        await manager.listen_redis(exam_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await manager.disconnect(websocket, exam_id)


# ── Error Handlers ──────────────────────────────────────────────────────────

from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "path": str(request.url),
        },
    )


# ── Root ────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint — returns service info and links to documentation."""
    return {
        "service": "Curriculum AI Agent",
        "version": "2.0.0",
        "docs": "/docs",
    }


# ── Run ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
