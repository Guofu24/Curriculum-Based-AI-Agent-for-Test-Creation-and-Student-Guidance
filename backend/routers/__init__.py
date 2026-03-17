from routers.auth import router as auth_router
from routers.courses import router as courses_router
from routers.documents import router as documents_router
from routers.exams import router as exams_router
from routers.export import router as export_router
from routers.generation import router as generation_router
from routers.guidance import router as guidance_router
from routers.textbooks import router as textbooks_router

__all__ = [
    "auth_router",
    "courses_router",
    "documents_router",
    "exams_router",
    "export_router",
    "generation_router",
    "guidance_router",
    "textbooks_router",
]
