"""Verify both the active app package and the compatibility shims."""

import sys

ACTIVE_CHECKS = [
    ("app.core.mvp", "from app.core.mvp import normalize_physics_subject"),
    ("app.repositories.document_repository", "from app.repositories.document_repository import DocumentRepository"),
    ("app.services.curriculum.scope_service", "from app.services.curriculum.scope_service import CurriculumScopeService"),
    ("app.services.exam_planning.spec_service", "from app.services.exam_planning.spec_service import ExamSpecService"),
    ("app.services.retrieval.scoped_retrieval_service", "from app.services.retrieval.scoped_retrieval_service import ScopedRetrievalService"),
    ("app.services.generation.mcq_generation_service", "from app.services.generation.mcq_generation_service import MCQGenerationService"),
    ("app.services.verification.mcq_verifier_service", "from app.services.verification.mcq_verifier_service import MCQVerifierService"),
    ("app.services.review.review_edit_service", "from app.services.review.review_edit_service import ReviewEditService"),
    ("app.services.exams.service", "from app.services.exams.service import ExamService"),
    ("app.api.routers.documents", "from app.api.routers.documents import router as documents_router"),
    ("app.api.routers.generation", "from app.api.routers.generation import router as generation_router"),
    ("app.api.routers.exams", "from app.api.routers.exams import router as exams_router"),
]

COMPATIBILITY_CHECKS = [
    ("core.mvp", "from core.mvp import normalize_physics_subject"),
    ("repositories.document_repository", "from repositories.document_repository import DocumentRepository"),
    ("services.curriculum.scope_service", "from services.curriculum.scope_service import CurriculumScopeService"),
    ("services.exam_planning.spec_service", "from services.exam_planning.spec_service import ExamSpecService"),
    ("services.retrieval.scoped_retrieval_service", "from services.retrieval.scoped_retrieval_service import ScopedRetrievalService"),
    ("services.generation.mcq_generation_service", "from services.generation.mcq_generation_service import MCQGenerationService"),
    ("services.verification.mcq_verifier_service", "from services.verification.mcq_verifier_service import MCQVerifierService"),
    ("services.editing.review_edit_service", "from services.editing.review_edit_service import ReviewEditService"),
    ("services.exam_service", "from services.exam_service import ExamService"),
    ("routers.documents", "from routers.documents import router as documents_router"),
    ("routers.generation", "from routers.generation import router as generation_router"),
    ("routers.exams", "from routers.exams import router as exams_router"),
]


def _run_checks(label: str, checks: list[tuple[str, str]]) -> list[str]:
    print(label)
    errors: list[str] = []
    for module_label, statement in checks:
        try:
            exec(statement, {})
            print(f"  OK {module_label}")
        except Exception as exc:  # pragma: no cover - helper script
            errors.append(f"FAIL {module_label}: {exc}")
    print()
    return errors


errors = [
    *_run_checks("Active package imports", ACTIVE_CHECKS),
    *_run_checks("Compatibility shim imports", COMPATIBILITY_CHECKS),
]

if errors:
    print(f"FAILED: {len(errors)} import error(s)")
    for error in errors:
        print(f"  {error}")
    sys.exit(1)

print("ACTIVE AND COMPATIBILITY IMPORTS VERIFIED")
