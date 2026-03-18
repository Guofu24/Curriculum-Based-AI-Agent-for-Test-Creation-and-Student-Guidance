"""
FastAPI Router Registry - MVP Only

Active routers for narrow MVP (Physics PDF, MCQ generation, strict scope):
- auth_router: authentication & authorization
- courses_router: course management
- documents_router: PDF upload & parsing
- exams_router: exam CRUD & versioning
- generation_router: MVP exam generation pipeline

Deprecated/Legacy routers (not exported, not mounted):
- backend/legacy/routers/guidance.py
- backend/legacy/routers/export.py
- backend/legacy/routers/textbooks.py
"""
from routers.auth import router as auth_router
from routers.courses import router as courses_router
from routers.documents import router as documents_router
from routers.exams import router as exams_router
from routers.generation import router as generation_router

__all__ = [
    "auth_router",
    "courses_router",
    "documents_router",
    "exams_router",
    "generation_router",
]
