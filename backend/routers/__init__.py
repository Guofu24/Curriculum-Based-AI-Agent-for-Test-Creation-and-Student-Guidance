from routers.auth import router as auth_router
from routers.textbooks import router as textbooks_router
from routers.exams import router as exams_router
from routers.generation import router as generation_router

__all__ = ["auth_router", "textbooks_router", "exams_router", "generation_router"]
