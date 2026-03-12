"""
Exams Router

Handles exam CRUD operations (list, get, delete).
Generation is handled by the generation router.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from routers.auth import get_current_user
from schemas.exam import ExamResponse, ExamListResponse, QuestionResponse, MCQOption
from services.exam_service import ExamService

router = APIRouter(prefix="/exams", tags=["exams"])


def _format_question(q) -> QuestionResponse:
    """Convert DB question to response schema."""
    options = None
    if q.options and isinstance(q.options, list):
        options = [MCQOption(label=o["label"], text=o["text"]) for o in q.options]

    return QuestionResponse(
        id=q.id,
        question_number=q.question_number,
        question_type=q.question_type.value,
        bloom_level=q.bloom_level.value,
        difficulty_score=q.difficulty_score,
        content=q.content,
        options=options,
        correct_answer=q.correct_answer,
        explanation=q.explanation,
        source_citations=q.source_chunks,
        is_validated=q.is_validated,
        quality_score_detail=q.quality_score_json,
        grounding_report_detail=q.grounding_report_json,
    )


@router.get("/", response_model=list[ExamListResponse])
async def list_exams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all exams for the current user."""
    service = ExamService(db)
    exams = await service.get_exams(current_user.id)
    return [
        ExamListResponse(
            id=e.id,
            title=e.title,
            textbook_id=e.textbook_id,
            exam_type=e.exam_type.value,
            difficulty=e.difficulty.value,
            status=e.status.value,
            chapters=e.chapters,
            total_questions=e.total_questions,
            quality_score=e.quality_score,
            created_at=e.created_at,
        )
        for e in exams
    ]


@router.get("/{exam_id}", response_model=ExamResponse)
async def get_exam(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get exam details with all questions."""
    service = ExamService(db)
    exam = await service.get_exam(exam_id, current_user.id)

    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    questions = sorted(exam.questions, key=lambda q: q.question_number)

    return ExamResponse(
        id=exam.id,
        title=exam.title,
        textbook_id=exam.textbook_id,
        exam_type=exam.exam_type.value,
        difficulty=exam.difficulty.value,
        status=exam.status.value,
        chapters=exam.chapters,
        variant_number=exam.variant_number,
        total_questions=exam.total_questions,
        quality_score=exam.quality_score,
        created_at=exam.created_at,
        questions=[_format_question(q) for q in questions],
        quality_scores=exam.quality_scores_json,
        grounding_reports=exam.grounding_reports_json,
        duplicate_groups=exam.duplicate_groups_json,
        provider_logs=exam.provider_logs_json,
        edit_impact_level=exam.edit_impact_level,
    )


@router.delete("/{exam_id}")
async def delete_exam(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an exam."""
    service = ExamService(db)
    deleted = await service.delete_exam(exam_id, current_user.id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Exam not found")

    return {"message": "Exam deleted successfully"}
