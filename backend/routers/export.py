"""
Export Router — Download exam in DOCX / JSON formats.

Endpoints:
  GET /export/{exam_id}/docx     — exam paper as DOCX
  GET /export/{exam_id}/docx-key — answer key as separate DOCX
  GET /export/{exam_id}/json     — exam data as JSON

Spec reference: §6.15
"""
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from routers.auth import get_current_user
from services.exam_service import ExamService
from services.export_service import ExportService

router = APIRouter(prefix="/export", tags=["export"])


def _slugify(text: str) -> str:
    """Convert text to a safe filename."""
    text = re.sub(r"[^\w\s\-]", "", text.lower())
    return re.sub(r"[\s]+", "_", text.strip())[:80]


async def _load_exam_for_export(exam_id: str, user_id: str, db: AsyncSession):
    """Load exam with all questions for export."""
    service = ExamService(db)
    exam = await service.get_exam(exam_id, user_id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Get active version questions
    version = None
    if getattr(exam, "current_version", None):
        version = exam.current_version
    elif exam.versions:
        versions = list(exam.versions)
        if versions:
            version = max(versions, key=lambda v: v.version_number)

    questions = []
    if version and version.questions:
        questions = sorted(version.questions, key=lambda q: q.question_number)
    elif exam.questions:
        questions = sorted(exam.questions, key=lambda q: q.question_number)

    return exam, questions, version


@router.get("/{exam_id}/docx")
async def export_exam_docx(
    exam_id: str,
    include_answers: bool = Query(False, description="Include answers in the document"),
    include_rubric: bool = Query(False, description="Include rubric for essay questions"),
    include_explanation: bool = Query(False, description="Include explanations"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Export exam as DOCX file.

    Optional query params:
      - include_answers: show correct answers
      - include_rubric: include rubric for essay questions
      - include_explanation: add explanation section
    """
    exam, questions, version = await _load_exam_for_export(exam_id, current_user.id, db)

    if not questions:
        raise HTTPException(status_code=400, detail="Exam has no questions to export")

    exporter = ExportService(exam, questions, version)
    buffer = exporter.export_docx(
        include_answers=include_answers,
        include_rubric=include_rubric,
        include_explanation=include_explanation,
    )

    filename = f"{_slugify(exam.title)}.docx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{exam_id}/docx-key")
async def export_answer_key_docx(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export answer key as a separate DOCX file."""
    exam, questions, version = await _load_exam_for_export(exam_id, current_user.id, db)

    if not questions:
        raise HTTPException(status_code=400, detail="Exam has no questions to export")

    exporter = ExportService(exam, questions, version)
    buffer = exporter.export_answer_key_docx()

    filename = f"{_slugify(exam.title)}_dap_an.docx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{exam_id}/json")
async def export_exam_json(
    exam_id: str,
    include_answers: bool = Query(True, description="Include answers"),
    include_evidence: bool = Query(False, description="Include source evidence"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export exam data as JSON for internal reuse or external tool import."""
    exam, questions, version = await _load_exam_for_export(exam_id, current_user.id, db)

    if not questions:
        raise HTTPException(status_code=400, detail="Exam has no questions to export")

    exporter = ExportService(exam, questions, version)
    buffer = exporter.export_json(
        include_answers=include_answers,
        include_evidence=include_evidence,
    )

    filename = f"{_slugify(exam.title)}.json"
    return StreamingResponse(
        buffer,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
