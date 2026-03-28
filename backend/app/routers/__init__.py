"""API routers package."""

from app.routers.auth import router as auth_router
from app.routers.documents import router as documents_router
from app.routers.exams import router as exams_router

__all__ = [
    "auth_router",
    "documents_router",
    "exams_router",
]

# Aliases matching main.py imports
auth = __import__("app.routers.auth", fromlist=["router"]).router
documents = __import__("app.routers.documents", fromlist=["router"]).router
exams = __import__("app.routers.exams", fromlist=["router"]).router
