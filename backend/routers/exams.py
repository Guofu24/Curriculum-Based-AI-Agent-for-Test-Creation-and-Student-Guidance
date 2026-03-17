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
from schemas.exam import (
    EditOperationResponse,
    ExamListResponse,
    ExamResponse,
    ExamVersionResponse,
    MCQOption,
    QuestionResponse,
)
from services.exam_service import ExamService
from utils.security import require_roles
from models.user import UserRole

router = APIRouter(prefix="/exams", tags=["exams"])


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _format_question(q) -> QuestionResponse:
    """Convert DB question to response schema."""
    options = None
    if q.options and isinstance(q.options, list):
        options = [
            MCQOption(label=str(option.get("label", "")), text=str(option.get("text", "")))
            for option in q.options
            if isinstance(option, dict)
        ]

    return QuestionResponse(
        id=q.id,
        question_number=q.question_number,
        blueprint_cell_key=q.blueprint_cell_key,
        question_type=_enum_value(q.question_type),
        bloom_level=_enum_value(q.bloom_level),
        difficulty_score=q.difficulty_score,
        content=q.content,
        options=options,
        correct_answer=q.correct_answer,
        rubric=q.rubric_json,
        explanation=q.explanation,
        source_citations=q.source_chunks,
        source_evidence=q.source_evidence_json,
        scope_tags=q.scope_tags_json or [],
        warnings=q.warnings_json or [],
        verification_status=q.verification_status,
        is_human_edited=bool(q.is_human_edited),
        is_locked=bool(q.is_locked),
        is_validated=bool(q.is_validated),
        quality_score_detail=q.quality_score_json,
        grounding_report_detail=q.grounding_report_json,
    )


def _get_active_version(exam):
    if getattr(exam, "current_version", None):
        return exam.current_version
    versions = list(getattr(exam, "versions", []) or [])
    if not versions:
        return None
    return max(versions, key=lambda version: version.version_number)


def _format_version(version) -> dict:
    questions = sorted(version.questions or [], key=lambda question: question.question_number)
    operations = sorted(version.edit_operations or [], key=lambda operation: operation.created_at)
    return ExamVersionResponse(
        id=version.id,
        version_number=version.version_number,
        status=version.status,
        created_by=version.created_by,
        parent_version_id=version.parent_version_id,
        change_summary=version.change_summary,
        created_at=version.created_at,
        questions=[_format_question(question) for question in questions],
        edit_operations=[
            EditOperationResponse(
                id=operation.id,
                edit_type=operation.edit_type,
                target_question_id=operation.target_question_id,
                prompt_used=operation.prompt_used,
                created_at=operation.created_at,
            )
            for operation in operations
        ],
    ).model_dump()


def _format_exam(exam) -> ExamResponse:
    active_version = _get_active_version(exam)
    active_questions = sorted(
        (active_version.questions if active_version else []) or [],
        key=lambda question: question.question_number,
    )
    versions = sorted(list(exam.versions or []), key=lambda version: version.version_number)

    return ExamResponse(
        id=exam.id,
        title=exam.title,
        textbook_id=exam.textbook_id,
        course_id=exam.course_id,
        exam_type=_enum_value(exam.exam_type),
        difficulty=_enum_value(exam.difficulty),
        status=_enum_value(exam.status),
        chapters=exam.chapters or [],
        variant_number=exam.variant_number,
        total_questions=exam.total_questions,
        instructions=exam.instructions,
        output_language=exam.output_language,
        strict_scope_flag=bool(exam.strict_scope_flag),
        quality_score=exam.quality_score,
        created_at=exam.created_at,
        updated_at=exam.updated_at,
        published_at=exam.published_at,
        questions=[_format_question(question) for question in active_questions],
        exam_spec=exam.exam_spec_json,
        blueprint=exam.blueprint_json,
        selected_scope=exam.selected_scope_json,
        quality_scores=exam.quality_scores_json,
        grounding_reports=exam.grounding_reports_json,
        duplicate_groups=exam.duplicate_groups_json,
        provider_logs=exam.provider_logs_json,
        edit_impact_level=exam.edit_impact_level,
        edit_history=exam.edit_history_json,
        current_version=_format_version(active_version) if active_version else None,
        versions=[_format_version(version) for version in versions],
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
            course_id=e.course_id,
            exam_type=_enum_value(e.exam_type),
            difficulty=_enum_value(e.difficulty),
            status=_enum_value(e.status),
            chapters=e.chapters or [],
            total_questions=e.total_questions,
            strict_scope_flag=bool(e.strict_scope_flag),
            quality_score=e.quality_score,
            created_at=e.created_at,
            updated_at=e.updated_at,
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

    return _format_exam(exam)


@router.get("/{exam_id}/versions", response_model=list[ExamVersionResponse])
async def get_exam_versions(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ExamService(db)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    versions = sorted(list(exam.versions or []), key=lambda version: version.version_number)
    return [_format_version(version) for version in versions]


@router.post("/{exam_id}/publish", response_model=ExamResponse)
async def publish_exam(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    service = ExamService(db)
    try:
        exam = await service.publish_exam(exam_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _format_exam(exam)


@router.delete("/{exam_id}")
async def delete_exam(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """Delete an exam."""
    service = ExamService(db)
    deleted = await service.delete_exam(exam_id, current_user.id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Exam not found")

    return {"message": "Exam deleted successfully"}


class EditByPromptRequest:
    """Inline request model for edit-by-prompt."""

    def __init__(self, prompt: str):
        self.prompt = prompt


@router.post("/{exam_id}/edit-by-prompt", response_model=ExamResponse)
async def edit_exam_by_prompt(
    exam_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """
    Edit an exam using a natural language prompt.

    The prompt describes what changes to make (e.g., "Tăng độ khó các câu trắc nghiệm").
    The backend converts this into partial regeneration edits.

    Spec reference: §6.12
    """
    prompt = body.get("prompt", "")
    if not prompt or not prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    service = ExamService(db)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Convert prompt to a partial regeneration call
    # This delegates to the existing generation infrastructure
    from services.generation_service import GenerationService

    gen_service = GenerationService(db)
    try:
        updated_exam = await gen_service.partial_regenerate(
            exam_id=exam_id,
            user_id=current_user.id,
            edits=[{
                "question_ids": [],
                "edit_type": "regenerate",
                "edit_prompt": prompt.strip(),
            }],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Edit failed: {str(e)}")

    # Reload and return full exam
    refreshed = await service.get_exam(exam_id, current_user.id)
    if not refreshed:
        raise HTTPException(status_code=404, detail="Exam not found after edit")

    return _format_exam(refreshed)
