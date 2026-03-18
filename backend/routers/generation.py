"""
Generation Router

Handles MVP exam generation and scoped partial regeneration.
"""
import json
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from routers.auth import get_current_user
from schemas.exam import (
    EditOperationResponse,
    ExamGenerationRequest,
    ExamPartialRegenerateRequest,
    ExamResponse,
    ExamVersionResponse,
    FeedbackEventResponse,
    GenerationStep,
    QuestionResponse,
    MCQOption,
)
from services.exam_service import ExamService
from utils.security import require_roles
from models.user import UserRole

router = APIRouter(prefix="/generate", tags=["generation"])


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _format_question(q) -> QuestionResponse:
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


def _format_feedback_event(event) -> dict:
    return FeedbackEventResponse(
        id=event.id,
        signal_type=_enum_value(event.signal_type),
        severity=event.severity,
        question_id=event.question_id,
        payload=event.payload_json,
        created_at=event.created_at,
    ).model_dump()


def _format_version(version) -> dict:
    questions = sorted(version.questions or [], key=lambda question: question.question_number)
    operations = sorted(version.edit_operations or [], key=lambda operation: operation.created_at)
    feedback_events = sorted(version.feedback_events or [], key=lambda event: event.created_at)
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
        feedback_events=[_format_feedback_event(event) for event in feedback_events],
    ).model_dump()


def _format_exam(full_exam) -> ExamResponse:
    active_version = _get_active_version(full_exam)
    questions = sorted(
        (active_version.questions if active_version else []) or [],
        key=lambda question: question.question_number,
    )
    versions = sorted(list(full_exam.versions or []), key=lambda version: version.version_number)
    return ExamResponse(
        id=full_exam.id,
        title=full_exam.title,
        document_id=full_exam.textbook_id,
        course_id=full_exam.course_id,
        exam_type=_enum_value(full_exam.exam_type),
        difficulty=_enum_value(full_exam.difficulty),
        status=_enum_value(full_exam.status),
        chapters=full_exam.chapters or [],
        variant_number=full_exam.variant_number,
        total_questions=full_exam.total_questions,
        instructions=full_exam.instructions,
        output_language=full_exam.output_language,
        strict_scope_flag=bool(full_exam.strict_scope_flag),
        quality_score=full_exam.quality_score,
        created_at=full_exam.created_at,
        updated_at=full_exam.updated_at,
        published_at=full_exam.published_at,
        questions=[_format_question(question) for question in questions],
        exam_spec=full_exam.exam_spec_json,
        blueprint=full_exam.blueprint_json,
        selected_scope=full_exam.selected_scope_json,
        quality_scores=full_exam.quality_scores_json,
        grounding_reports=full_exam.grounding_reports_json,
        duplicate_groups=full_exam.duplicate_groups_json,
        provider_logs=full_exam.provider_logs_json,
        edit_impact_level=full_exam.edit_impact_level,
        edit_history=full_exam.edit_history_json,
        feedback_events=[
            _format_feedback_event(event)
            for event in sorted(list(full_exam.feedback_events or []), key=lambda item: item.created_at)
        ],
        current_version=_format_version(active_version) if active_version else None,
        versions=[_format_version(version) for version in versions],
    )


@router.post("/exam", response_model=ExamResponse)
async def generate_exam(
    request: ExamGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """
    Generate a new exam with the explicit MVP pipeline.

    Flow:
    1. Resolve scope -> 2. Build exam spec -> 3. Plan blueprint
    4. Retrieve evidence -> 5. Generate MCQ -> 6. Verify -> 7. Save version
    """
    service = ExamService(db)

    try:
        exam = await service.generate_exam(current_user.id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

    # Re-fetch with questions
    full_exam = await service.get_exam(exam.id, current_user.id)
    return _format_exam(full_exam)


@router.post("/exam/stream")
async def generate_exam_stream(
    request: ExamGenerationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """
    Generate exam with Server-Sent Events (SSE) progress updates.
    """
    async def event_stream():
        steps = [
            GenerationStep(step=1, name="Building exam spec", status="pending"),
            GenerationStep(step=2, name="Planning blueprint", status="pending"),
            GenerationStep(step=3, name="Retrieving evidence", status="pending"),
            GenerationStep(step=4, name="Generating and validating", status="pending"),
            GenerationStep(step=5, name="Finalizing exam", status="pending"),
        ]

        # Emit initial state
        for s in steps:
            yield f"data: {s.model_dump_json()}\n\n"

        # Step 1: Requirement parsing / exam spec
        steps[0].status = "running"
        yield f"data: {steps[0].model_dump_json()}\n\n"
        await asyncio.sleep(0.5)  # allow frontend to render
        steps[0].status = "completed"
        yield f"data: {steps[0].model_dump_json()}\n\n"

        # Step 2: Blueprint planning
        steps[1].status = "running"
        yield f"data: {steps[1].model_dump_json()}\n\n"
        await asyncio.sleep(0.2)
        steps[1].status = "completed"
        yield f"data: {steps[1].model_dump_json()}\n\n"

        # Step 3: Retrieval
        steps[2].status = "running"
        yield f"data: {steps[2].model_dump_json()}\n\n"
        await asyncio.sleep(0.2)
        steps[2].status = "completed"
        yield f"data: {steps[2].model_dump_json()}\n\n"

        # Step 4: Generation + validation (starts the actual generation)
        steps[3].status = "running"
        yield f"data: {steps[3].model_dump_json()}\n\n"

        try:
            service = ExamService(db)
            exam = await service.generate_exam(current_user.id, request)

            steps[3].status = "completed"
            yield f"data: {steps[3].model_dump_json()}\n\n"

            # Step 5: Finalizing
            steps[4].status = "completed"
            steps[4].message = exam.id  # send exam ID
            yield f"data: {steps[4].model_dump_json()}\n\n"

            # Final: send complete signal
            yield f"data: {json.dumps({'type': 'complete', 'exam_id': exam.id})}\n\n"

        except Exception as e:
            error_step = next((s for s in steps if s.status == "running"), steps[-1])
            error_step.status = "failed"
            error_step.message = str(e)
            yield f"data: {error_step.model_dump_json()}\n\n"
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/partial-regenerate", response_model=ExamResponse)
async def partial_regenerate(
    request: ExamPartialRegenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    """
    Regenerate specific questions in an existing exam version.
    """
    service = ExamService(db)

    try:
        exam = await service.partial_regenerate(current_user.id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    full_exam = await service.get_exam(exam.id, current_user.id)
    return _format_exam(full_exam)
