"""Quick verification that the active MVP modules import correctly."""

import sys

errors: list[str] = []

checks = [
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

for label, statement in checks:
    try:
        exec(statement, {})
        print(f"OK {label}")
    except Exception as exc:  # pragma: no cover - helper script
        errors.append(f"FAIL {label}: {exc}")

print()
if errors:
    print(f"FAILED: {len(errors)} import error(s)")
    for error in errors:
        print(f"  {error}")
    sys.exit(1)

print("ACTIVE MVP IMPORTS VERIFIED")
