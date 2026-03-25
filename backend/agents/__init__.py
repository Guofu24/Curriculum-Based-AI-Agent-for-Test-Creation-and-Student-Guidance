"""
Compatibility exports for the historical `agents` package.

The active orchestration/runtime code now lives under `app.services` and
`app.core.runtime_models`.
"""

from app.core.runtime_models import ChunkAssignment, ExamBlueprint, GeneratedQuestion
from app.services.documents.processor import DocumentProcessorAgent
from app.services.exam_planning.blueprint_service import BlueprintAgent
from app.services.generation.llm_backend import LLMBackend, ProviderLog
from app.services.generation.llm_router import create_llm
from app.services.generation.question_generator import QuestionGeneratorAgent
from app.services.retrieval.retrieval_engine import RetrievalAgent
from app.services.verification.grounding_checker import GroundingChecker
from app.services.verification.validator import ValidatorAgent

__all__ = [
    "BlueprintAgent",
    "ChunkAssignment",
    "DocumentProcessorAgent",
    "ExamBlueprint",
    "GeneratedQuestion",
    "GroundingChecker",
    "LLMBackend",
    "ProviderLog",
    "QuestionGeneratorAgent",
    "RetrievalAgent",
    "ValidatorAgent",
    "create_llm",
]

