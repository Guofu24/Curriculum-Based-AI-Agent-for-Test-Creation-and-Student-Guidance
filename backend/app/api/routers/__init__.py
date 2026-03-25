"""
Active FastAPI router registry.

Only routers exported here are mounted by the active backend runtime.
Legacy routers remain under `backend/legacy/routers` and are not mounted.
"""

from app.api.routers.auth import router as auth_router
from app.api.routers.courses import router as courses_router
from app.api.routers.documents import router as documents_router
from app.api.routers.exams import router as exams_router
from app.api.routers.generation import router as generation_router
from app.api.routers.playbook import router as playbook_router

__all__ = [
    "auth_router",
    "courses_router",
    "documents_router",
    "exams_router",
    "generation_router",
    "playbook_router",
]
