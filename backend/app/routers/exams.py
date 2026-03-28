"""Exam router: generate, list, detail, edit, export - aligned with frontend API."""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import uuid

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.services.exam_service import ExamService, ExamServiceError
from app.schemas.exam import (
    ExamConfigRequest,
    ExamGenerateResponse,
    EditQuestionRequest,
    PromptEditRequest,
    RegenerateRequest,
    ExportFormat,
    RestoreSnapshotRequest,
)
from app.dependencies import get_current_user
from app.models.user import User
from app.tasks.exam_task import generate_exam_task
from app.utils.export import export_exam_to_pdf, export_exam_to_docx

router = APIRouter(prefix="/api/v1/exams", tags=["Exams"])


def _exam_to_list_item(exam) -> dict:
    """Convert Exam model to dict matching frontend's ExamListItem."""
    questions = exam.questions or []
    mcq_count = sum(1 for q in questions if q.get("type") == "mcq" or q.get("question_type") == "mcq")
    essay_count = sum(1 for q in questions if q.get("type") == "essay" or q.get("question_type") == "essay")

    return {
        "id": str(exam.id),
        "title": exam.title,
        "document_id": str(exam.document_id) if exam.document_id else "",
        "course_id": str(exam.course_id) if exam.course_id else None,
        "exam_type": exam.exam_type or "mixed",
        "difficulty": exam.difficulty or "medium",
        "status": exam.status or "draft",
        "chapters": exam.chapters or [],
        "total_questions": exam.total_questions or mcq_count + essay_count,
        "strict_scope_flag": exam.strict_scope_flag if exam.strict_scope_flag is not None else True,
        "quality_score": float(exam.quality_score) if exam.quality_score else None,
        "current_version_number": None,  # TODO: join with ExamVersion
        "version_count": exam.version_count or 1,
        "verifier_pass_rate": float(exam.verifier_pass_rate) if exam.verifier_pass_rate else None,
        "evidence_coverage_rate": float(exam.evidence_coverage_rate) if exam.evidence_coverage_rate else None,
        "warning_count": exam.warning_count or 0,
        "regenerate_count": exam.regenerate_count or 0,
        "human_edit_count": exam.human_edit_count or 0,
        "feedback_event_count": 0,  # TODO: count from feedback_events
        "created_at": exam.created_at.isoformat() if exam.created_at else None,
        "updated_at": exam.updated_at.isoformat() if exam.updated_at else None,
    }


def _exam_to_detail(exam, versions=None, feedback_events=None) -> dict:
    """Convert Exam model to dict matching frontend's Exam interface."""
    questions = exam.questions or []
    return {
        "id": str(exam.id),
        "title": exam.title,
        "document_id": str(exam.document_id) if exam.document_id else "",
        "course_id": str(exam.course_id) if exam.course_id else None,
        "exam_type": exam.exam_type or "mixed",
        "difficulty": exam.difficulty or "medium",
        "status": exam.status or "draft",
        "chapters": exam.chapters or [],
        "variant_number": exam.variant_number or 1,
        "total_questions": exam.total_questions or len(questions),
        "instructions": exam.instructions,
        "output_language": exam.output_language or "vi",
        "strict_scope_flag": exam.strict_scope_flag if exam.strict_scope_flag is not None else True,
        "quality_score": float(exam.quality_score) if exam.quality_score else None,
        "created_at": exam.created_at.isoformat() if exam.created_at else None,
        "updated_at": exam.updated_at.isoformat() if exam.updated_at else None,
        "published_at": exam.published_at.isoformat() if exam.published_at else None,
        "questions": questions,
        "exam_spec": exam.exam_spec,
        "blueprint": exam.blueprint,
        "selected_scope": exam.selected_scope,
        "quality_scores": exam.quality_scores,
        "grounding_reports": exam.grounding_reports,
        "duplicate_groups": exam.duplicate_groups,
        "provider_logs": exam.provider_logs,
        "feedback_events": feedback_events,
        "current_version": None,
        "versions": versions,
    }


def _version_to_dict(version) -> dict:
    """Convert ExamVersion to dict matching frontend's ExamVersion."""
    return {
        "id": str(version.id),
        "version_number": version.version_number,
        "status": version.status or "draft",
        "created_by": str(version.created_by) if version.created_by else "",
        "parent_version_id": str(version.parent_version_id) if version.parent_version_id else None,
        "change_summary": version.change_summary,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "questions": version.questions or [],
        "edit_operations": version.edit_operations or [],
        "feedback_events": [],  # TODO: join
    }


def _feedback_to_dict(event) -> dict:
    """Convert FeedbackEvent to dict matching frontend's FeedbackEvent."""
    return {
        "id": str(event.id),
        "exam_id": str(event.exam_id),
        "exam_title": None,
        "exam_version_id": str(event.exam_version_id) if event.exam_version_id else None,
        "version_number": None,
        "actor_id": str(event.actor_id) if event.actor_id else None,
        "signal_type": event.signal_type or "",
        "severity": event.severity or "info",
        "workflow_stage": event.workflow_stage,
        "event_stage": event.workflow_stage,
        "event_source": event.event_source,
        "source_type": event.source_type,
        "source_ref": event.source_ref,
        "review_status": event.review_status,
        "reviewed_by_human": event.reviewed_by_human or False,
        "question_id": str(event.question_id) if event.question_id else None,
        "error_categories": event.error_categories or [],
        "before_snapshot_ref": event.before_snapshot_ref,
        "after_snapshot_ref": event.after_snapshot_ref,
        "linked_eval_sample_id": None,
        "payload": event.payload,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.post("/generate", response_model=ExamGenerateResponse)
async def generate_exam(
    config: ExamConfigRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Start exam generation. Creates exam record and triggers Celery task."""
    service = ExamService(db, redis)

    # Validate bloom distribution sums to 100
    bloom = config.bloom_distribution
    total = bloom.nhan_biet + bloom.thong_hieu + bloom.van_dung + bloom.van_dung_cao
    if total != 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bloom distribution must sum to 100%, got {total}%",
        )

    # Create exam record
    exam = await service.create_exam(
        user_id=current_user.id,
        document_id=config.document_id,
        title=config.title,
        scope=config.scope,
        exam_config={
            "exam_type": config.exam_type,
            "mcq_count": config.mcq_count,
            "essay_count": config.essay_count,
            "bloom_distribution": config.bloom_distribution.model_dump(),
            "user_prompt": config.user_prompt,
            "extra_instructions": config.extra_instructions,
        },
    )

    job_id = str(uuid.uuid4())
    generate_exam_task.delay(
        exam_id=str(exam.id),
        user_id=str(current_user.id),
        document_id=str(config.document_id),
        scope=config.scope,
        exam_config=exam.exam_config,
        user_prompt=config.user_prompt,
        extra_instructions=config.extra_instructions,
    )

    return ExamGenerateResponse(
        exam_id=exam.id,
        job_id=job_id,
        message="Exam generation started.",
    )


@router.get("", response_model=list[dict])
async def list_exams(
    page: int = 1,
    limit: int = 20,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """List all exams for the current user. Returns list matching frontend's ExamListItem[]."""
    service = ExamService(db, redis)
    exams, _ = await service.list_exams(
        user_id=current_user.id,
        page=page,
        limit=limit,
        status=status,
    )
    return [_exam_to_list_item(e) for e in exams]


@router.get("/{exam_id}", response_model=dict)
async def get_exam(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get exam details. Returns dict matching frontend's Exam interface."""
    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)

    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    # Load versions
    versions = await service.get_exam_history(exam_id, current_user.id)
    version_dicts = [_version_to_dict(v) for v in versions]

    # Load feedback events
    feedback_events = await service.get_feedback_events(exam_id, current_user.id)
    feedback_dicts = [_feedback_to_dict(f) for f in feedback_events]

    return _exam_to_detail(exam, versions=version_dicts, feedback_events=feedback_dicts)


@router.get("/{exam_id}/versions", response_model=list[dict])
async def get_exam_versions(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get exam versions (history). Returns list matching frontend's ExamVersion[]."""
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    versions = await service.get_exam_history(exam_id, current_user.id)
    return [_version_to_dict(v) for v in versions]


@router.get("/{exam_id}/feedback", response_model=list[dict])
async def get_exam_feedback(
    exam_id: UUID,
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get feedback events for an exam. Returns list matching frontend's FeedbackEvent[]."""
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    events = await service.get_feedback_events(exam_id, current_user.id, page, limit)
    return [_feedback_to_dict(f) for f in events]


@router.post("/{exam_id}/publish")
async def publish_exam(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Publish an exam."""
    service = ExamService(db, redis)
    try:
        await service.publish_exam(exam_id, current_user.id)
    except ExamServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Exam published successfully"}


@router.delete("/{exam_id}")
async def delete_exam(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Delete an exam."""
    service = ExamService(db, redis)
    deleted = await service.delete_exam(exam_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")
    return {"message": "Exam deleted successfully"}


# ── Global quality & feedback endpoints ───────────────────────────────────────

@router.get("/quality-summary")
async def get_quality_summary(
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get quality metrics summary. Returns dict matching frontend's QualitySummary."""
    service = ExamService(db, redis)
    return await service.get_quality_summary(current_user.id)


@router.get("/feedback-summary")
async def get_feedback_summary(
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get feedback store summary. Returns dict matching frontend's FeedbackStoreSummary."""
    service = ExamService(db, redis)
    return await service.get_feedback_store_summary(current_user.id)


@router.get("/feedback-store")
async def get_feedback_store(
    page: int = 1,
    limit: int = 50,
    severity: str | None = None,
    review_status: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get filtered feedback events. Returns list matching frontend's FeedbackEvent[]."""
    service = ExamService(db, redis)
    events, total = await service.get_feedback_store(
        user_id=current_user.id,
        page=page,
        limit=limit,
        severity=severity,
        review_status=review_status,
    )
    return {
        "items": [_feedback_to_dict(f) for f in events],
        "total": total,
        "page": page,
        "limit": limit,
    }


# ── Existing endpoints (kept for compatibility) ─────────────────────────────────

@router.patch("/{exam_id}/questions/{question_id}")
async def edit_question(
    exam_id: UUID,
    question_id: str,
    request: EditQuestionRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Edit a single question (inline edit)."""
    service = ExamService(db, redis)
    try:
        await service.update_question(exam_id, question_id, request.updates)
    except ExamServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Question updated"}


@router.post("/{exam_id}/edit-prompt")
async def edit_via_prompt(
    exam_id: UUID,
    request: PromptEditRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Edit exam via natural language prompt."""
    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    from app.agents.orchestrator import OrchestratorAgent
    orchestrator = OrchestratorAgent(redis=redis, db_session=db)
    result = await orchestrator.edit_via_prompt(
        exam_id=str(exam_id),
        user_id=str(current_user.id),
        prompt=request.prompt,
    )
    return result


@router.post("/{exam_id}/regenerate")
async def regenerate_exam(
    exam_id: UUID,
    question_ids: list[str] | None = None,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Regenerate questions (all or specific)."""
    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    await service.regenerate_questions(exam_id, question_ids)
    generate_exam_task.delay(
        exam_id=str(exam_id),
        user_id=str(current_user.id),
        document_id=str(exam.document_id),
        scope=exam.scope or [],
        exam_config=exam.exam_config or {},
    )
    return {"message": "Regeneration started"}


@router.post("/{exam_id}/export")
async def export_exam(
    exam_id: UUID,
    format: ExportFormat,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Export exam to PDF or DOCX."""
    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    exam_data = {
        "title": exam.title or "Đề kiểm tra",
        "scope": exam.scope or [],
        "questions": exam.questions or [],
    }

    if format.format == "pdf":
        content = export_exam_to_pdf(exam_data)
        filename = f"{exam.title or 'exam'}.pdf"
        media_type = "application/pdf"
    else:
        content = export_exam_to_docx(exam_data)
        filename = f"{exam.title or 'exam'}.docx"
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{exam_id}/history")
async def get_exam_history(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get exam history snapshots."""
    service = ExamService(db, redis)
    versions = await service.get_exam_history(exam_id, current_user.id)
    return [_version_to_dict(v) for v in versions]


@router.post("/{exam_id}/history/{history_id}/restore")
async def restore_snapshot(
    exam_id: UUID,
    history_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Restore exam to a previous snapshot."""
    service = ExamService(db, redis)
    try:
        await service.restore_snapshot(exam_id, history_id, current_user.id)
    except ExamServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "Snapshot restored"}


# ── HITL Checkpoint Endpoints ───────────────────────────────────────────────────

from app.schemas.exam import BlueprintApprovalRequest


@router.post("/{exam_id}/approve-blueprint")
async def approve_blueprint(
    exam_id: UUID,
    request: BlueprintApprovalRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    HITL Checkpoint 1: Blueprint approval.
    Called after user reviews the generated blueprint.
    If approved=True: proceed to question generation.
    If approved=False: re-generate outline with feedback.
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    from app.agents.orchestrator import OrchestratorAgent
    orchestrator = OrchestratorAgent(redis=redis, db_session=db)

    result = await orchestrator.approve_blueprint(
        exam_id=str(exam_id),
        user_id=str(current_user.id),
        approved=request.approved,
        feedback=request.feedback,
    )
    return result


class ExamReviewRequest(BaseModel):
    """Schema for full exam review submission."""
    approved: bool
    feedback: str | None = None
    direct_edits: list[dict] | None = None

    class Config:
        from_attributes = True


@router.post("/{exam_id}/submit-review")
async def submit_exam_review(
    exam_id: UUID,
    request: ExamReviewRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    HITL Checkpoint 2: Full exam review.
    Called after user reviews the generated questions.
    If approved=True: mark exam as ready for export.
    If approved=False: re-generate with feedback or direct edits.
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    from app.agents.orchestrator import OrchestratorAgent
    orchestrator = OrchestratorAgent(redis=redis, db_session=db)

    result = await orchestrator.submit_review(
        exam_id=str(exam_id),
        user_id=str(current_user.id),
        approved=request.approved,
        feedback=request.feedback,
        direct_edits=request.direct_edits,
    )
    return result
