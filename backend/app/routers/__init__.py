"""API routers package."""

from fastapi import APIRouter


def _strip_legacy_example_kw(method):
    """FastAPI compatibility shim: ignore legacy `example=` decorator metadata."""

    def wrapper(self, path: str, *args, **kwargs):
        kwargs.pop("example", None)
        return method(self, path, *args, **kwargs)

    return wrapper


APIRouter.get = _strip_legacy_example_kw(APIRouter.get)
APIRouter.post = _strip_legacy_example_kw(APIRouter.post)
APIRouter.put = _strip_legacy_example_kw(APIRouter.put)
APIRouter.patch = _strip_legacy_example_kw(APIRouter.patch)
APIRouter.delete = _strip_legacy_example_kw(APIRouter.delete)

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
