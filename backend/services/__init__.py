"""
Compatibility exports for the pre-refactor `services` package.

The active domain-first service graph now lives under `app.services`.
"""

from app.services.courses.service import CourseService
from app.services.documents.service import DocumentService
from app.services.exams.service import ExamService
from app.services.feedback.feedback_event_service import FeedbackEventService
from app.services.retrieval.rag_service import RAGService

__all__ = [
    "CourseService",
    "DocumentService",
    "ExamService",
    "FeedbackEventService",
    "RAGService",
]
