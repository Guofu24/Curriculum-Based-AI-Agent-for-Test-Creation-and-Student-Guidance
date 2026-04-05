"""Exam router: generate, list, detail, edit, export - aligned with frontend API."""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import uuid
from datetime import date

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.core.config import get_settings
from app.core.config import get_settings as _get_settings
from app.services.exam_service import ExamService, ExamServiceError
from app.schemas.exam import (
    ExamConfigRequest,
    ExamGenerateResponse,
    EditQuestionRequest,
    PromptEditRequest,
    RegenerateRequest,
    RestoreSnapshotRequest,
    BlueprintApprovalRequest,
    BlueprintApprovalResponse,
    BlueprintRejectionRequest,
    BlueprintRejectionResponse,
    ReviewDataResponse,
    ExportPreviewResponse,
    ExamReviewRequest,
    ExamReviewResponse,
)
from app.dependencies import get_current_user
from app.models.user import User
from app.tasks.exam_task import generate_exam_task
from app.utils.export import ExamExporter

import io

router = APIRouter(prefix="/api/v1/exams", tags=["Exams"])


# ── Rate limit helper (G13) ───────────────────────────────────────────────────
MAX_GENERATES_PER_DAY = _get_settings().MAX_GENERATES_PER_DAY


async def check_generate_rate_limit(redis: RedisClient, user_id: str) -> None:
    """
    G13: Rate limit — max 10 exam generations per user per day.
    incr first, expire only if count==1 (avoids resetting TTL on each request).
    """
    key = f"ratelimit:generate:{user_id}:{date.today().isoformat()}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 86400)
    if count > MAX_GENERATES_PER_DAY:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Đã vượt giới hạn {MAX_GENERATES_PER_DAY} lần tạo đề/ngày. Vui lòng thử lại sau.",
        )


def _exam_to_list_item(exam) -> dict:
    """Convert Exam model to dict matching frontend's ExamListItem."""
    questions = exam.questions or []
    mcq_count = sum(1 for q in questions if q.get("type") == "mcq" or q.get("question_type") == "mcq")
    essay_count = sum(1 for q in questions if q.get("type") == "essay" or q.get("question_type") == "essay")

    # chapters: FE expects number[] but backend stores string[].
    # Return both for compatibility.
    chapters_str: list[str] = exam.chapters or []
    chapters_num: list[int] = [i + 1 for i in range(len(chapters_str))]

    return {
        "id": str(exam.id),
        "title": exam.title,
        "document_id": str(exam.document_id) if exam.document_id else "",
        "course_id": str(exam.course_id) if exam.course_id else None,
        "exam_type": exam.exam_type or "mixed",
        "difficulty": exam.difficulty or "medium",
        "status": exam.status or "draft",
        "chapters": chapters_str,  # backend format (string titles)
        "chapters_num": chapters_num,  # FE compatibility (number indices)
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
    chapters_str: list[str] = exam.chapters or []
    chapters_num: list[int] = [i + 1 for i in range(len(chapters_str))]

    return {
        "id": str(exam.id),
        "title": exam.title,
        "document_id": str(exam.document_id) if exam.document_id else "",
        "course_id": str(exam.course_id) if exam.course_id else None,
        "exam_type": exam.exam_type or "mixed",
        "difficulty": exam.difficulty or "medium",
        "status": exam.status or "draft",
        "chapters": chapters_str,  # backend format (string titles)
        "chapters_num": chapters_num,  # FE compatibility (number indices)
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
    snapshot = getattr(version, "snapshot", None) or {}
    return {
        "id": str(version.id),
        "version_number": getattr(version, "version_number", None) or 1,
        "status": getattr(version, "status", None) or snapshot.get("status") or "draft",
        "created_by": str(getattr(version, "created_by", "") or ""),
        "parent_version_id": str(getattr(version, "parent_version_id", None)) if getattr(version, "parent_version_id", None) else None,
        "change_summary": getattr(version, "change_summary", None) or getattr(version, "change_description", None),
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "questions": getattr(version, "questions", None) or snapshot.get("questions", []),
        "edit_operations": getattr(version, "edit_operations", None) or [],
        "feedback_events": [],  # TODO: join
    }


def _feedback_to_dict(event) -> dict:
    """Convert FeedbackEvent to dict matching frontend's FeedbackEvent."""
    if isinstance(event, dict):
        return event

    return {
        "id": str(event.id),
        "exam_id": str(getattr(event, "exam_id", "")),
        "exam_title": None,
        "exam_version_id": str(getattr(event, "exam_version_id", None)) if getattr(event, "exam_version_id", None) else None,
        "version_number": None,
        "actor_id": str(getattr(event, "actor_id", None)) if getattr(event, "actor_id", None) else None,
        "signal_type": getattr(event, "signal_type", "") or "",
        "severity": getattr(event, "severity", "info") or "info",
        "workflow_stage": getattr(event, "workflow_stage", None),
        "event_stage": getattr(event, "workflow_stage", None),
        "event_source": getattr(event, "event_source", None),
        "source_type": getattr(event, "source_type", None),
        "source_ref": getattr(event, "source_ref", None),
        "review_status": getattr(event, "review_status", None),
        "reviewed_by_human": getattr(event, "reviewed_by_human", False) or False,
        "question_id": str(getattr(event, "question_id", None)) if getattr(event, "question_id", None) else None,
        "error_categories": getattr(event, "error_categories", None) or [],
        "before_snapshot_ref": getattr(event, "before_snapshot_ref", None),
        "after_snapshot_ref": getattr(event, "after_snapshot_ref", None),
        "linked_eval_sample_id": None,
        "payload": getattr(event, "payload", None),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


@router.post(
    "/generate",
    response_model=ExamGenerateResponse,
    summary="Start exam generation (G13 rate-limited)",
    description="Creates an exam record and dispatches a Celery task to run the full "
                 "multi-agent generation pipeline (retrieval → outline → HITL1 → "
                 "build → validate → HITL2 → export preview). "
                 "Rate limited to **10 generations per user per day** (G13). "
                 "WebSocket events stream to `/ws/exam/{exam_id}` during generation.",
    responses={
        200: {"description": "Exam generation job started, exam_id returned"},
        400: {"description": "Bloom distribution does not sum to 100%, or invalid config"},
        401: {"description": "Authentication required"},
        429: {"description": "Rate limit exceeded — max 10 generations/day"},
        422: {"description": "Validation error in request body"},
    },
    tags=["Exams"],
    example={
        "document_id": "550e8400-e29b-41d4-a716-446655440000",
        "scope": ["Chương 1", "Chương 2"],
        "exam_type": "mixed",
        "mcq_count": 10,
        "essay_count": 2,
        "bloom_distribution": {
            "nhan_biet": 20,
            "thong_hieu": 30,
            "van_dung": 30,
            "van_dung_cao": 20,
        },
        "user_prompt": "Tạo đề kiểm tra 1 tiết Hóa học lớp 11, phạm vi từ bảng tuần hoàn",
        "strict_scope_flag": True,
    },
)
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

    # G13: Check rate limit before creating exam
    await check_generate_rate_limit(redis, str(current_user.id))

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
        websocket_url=f"{get_settings().ws_base_url}/ws/exam/{exam.id}",
    )


@router.get(
    "",
    response_model=list[dict],
    summary="List all exams for current user",
    description="Returns a paginated list of exams owned by the current user. "
                 "Supports filtering by status. Exams are sorted by creation date (newest first).",
    responses={
        200: {"description": "Paginated list of exams (ExamListItem[])"},
        401: {"description": "Authentication required"},
    },
    tags=["Exams"],
)
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


@router.get(
    "/{exam_id}",
    response_model=dict,
    summary="Get exam details",
    description="Returns full exam data including questions, versions, and feedback events "
                 "matching frontend's Exam interface.",
    responses={
        200: {"description": "Full exam detail"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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


@router.get(
    "/{exam_id}/versions",
    response_model=list[dict],
    summary="Get exam version history",
    description="Returns the version history (snapshots) for an exam, "
                 "sorted by version number descending (newest first).",
    responses={
        200: {"description": "List of exam versions (ExamVersion[])"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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


@router.get(
    "/{exam_id}/feedback",
    response_model=list[dict],
    summary="Get feedback events for an exam",
    description="Returns paginated feedback events for an exam, "
                 "sorted by creation date (newest first).",
    responses={
        200: {"description": "List of feedback events (FeedbackEvent[])"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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


@router.post(
    "/{exam_id}/publish",
    summary="Publish an exam",
    description="Marks the exam as published. Also persists teacher preferences "
                 "(bloom distribution, exam type, subject focus) to long-term memory (G14). "
                 "A FeedbackEvent with signal_type='publish' is logged.",
    responses={
        200: {"description": "Exam published successfully"},
        400: {"description": "Publish failed — exam may not be ready"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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


@router.delete(
    "/{exam_id}",
    summary="Delete an exam",
    description="Permanently deletes an exam and its version history. "
                 "Cannot be undone.",
    responses={
        200: {"description": "Exam deleted successfully"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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

@router.get(
    "/quality-summary",
    summary="Get quality metrics summary",
    description="Returns aggregated quality metrics across all user's exams: "
                 "verifier pass rate, evidence coverage rate, top error categories, "
                 "and recent warnings. Useful for dashboard analytics.",
    responses={
        200: {"description": "Quality metrics summary (QualitySummary)"},
        401: {"description": "Authentication required"},
    },
    tags=["Exams"],
)
async def get_quality_summary(
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get quality metrics summary. Returns dict matching frontend's QualitySummary."""
    service = ExamService(db, redis)
    return await service.get_quality_summary(current_user.id)


@router.get(
    "/feedback-summary",
    summary="Get feedback store summary",
    description="Returns aggregated feedback store metrics: total events, "
                 "reviewed/accepted/rejected/corrected counts, top signal types, "
                 "top error categories, and recent events.",
    responses={
        200: {"description": "Feedback store summary (FeedbackStoreSummary)"},
        401: {"description": "Authentication required"},
    },
    tags=["Exams"],
)
async def get_feedback_summary(
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Get feedback store summary. Returns dict matching frontend's FeedbackStoreSummary."""
    service = ExamService(db, redis)
    return await service.get_feedback_store_summary(current_user.id)


@router.get(
    "/feedback-store",
    summary="Get filtered feedback store across all user exams",
    description="Returns paginated feedback events across all user exams with optional "
                 "filters by severity and review_status.",
    responses={
        200: {"description": "Paginated feedback events with total count"},
        401: {"description": "Authentication required"},
    },
    tags=["Exams"],
)
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

@router.patch(
    "/{exam_id}/questions/{question_id}",
    summary="Edit a single question inline",
    description="Apply a partial update to a specific question. "
                 "Only the fields in `updates` dict are modified. "
                 "Logs a FeedbackEvent with signal_type='edit_direct'.",
    responses={
        200: {"description": "Question updated successfully"},
        400: {"description": "Question not found or update failed"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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
        await service.update_question(exam_id, question_id, request.updates, current_user.id)
    except ExamServiceError as e:
        error_msg = str(e)
        if "Access denied" in error_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    return {"message": "Question updated"}


@router.post(
    "/{exam_id}/edit-prompt",
    summary="Edit exam via natural language prompt",
    description="Analyzes the user's prompt and determines the appropriate edits "
                 "(regenerate specific questions, update metadata, etc.). "
                 "Uses LLM to plan the edit, then calls BuilderAgent if regeneration needed. "
                 "Preserves exam_config_original so only targeted changes are made.",
    responses={
        200: {"description": "Edit planned and executed"},
        400: {"description": "Session not found or edit planning failed"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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


@router.post(
    "/{exam_id}/regenerate",
    summary="Regenerate questions (all or specific)",
    description="Re-generates questions either for all slots or only the specified question_ids. "
                 "Dispatches a Celery task to re-run the generation pipeline. "
                 "Logs a FeedbackEvent with signal_type='regenerate_requested'. "
                 "Use this to fix quality issues detected during review.",
    responses={
        200: {"description": "Regeneration task dispatched"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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

    await service.regenerate_questions(exam_id, question_ids, current_user.id)
    # Pass question_ids so the orchestrator knows which questions to regenerate
    generate_exam_task.delay(
        exam_id=str(exam_id),
        user_id=str(current_user.id),
        document_id=str(exam.document_id),
        scope=exam.scope or [],
        exam_config={**(exam.exam_config or {}), "regenerate_question_ids": question_ids},
    )
    return {"message": "Regeneration started"}


# ── Export PDF / DOCX ───────────────────────────────────────────────────────────

@router.get(
    "/{exam_id}/export/pdf",
    summary="Export exam as PDF (G12)",
    description="Generates a PDF file of the exam using WeasyPrint. "
                 "**include_answers=False** → bản học sinh (no answer key). "
                 "**include_answers=True** → bản giáo viên (includes answer key, "
                 "explanations, and essay rubric). "
                 "**include_blueprint=True** → adds Bloom distribution table at the top. "
                 "PDF is limited to 10MB; returns 400 if exceeded.",
    responses={
        200: {
            "description": "PDF file (application/pdf)",
            "content": {"application/pdf": {}},
        },
        400: {"description": "PDF exceeds 10MB limit or exam not found"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
async def export_pdf(
    exam_id: UUID,
    include_answers: bool = False,
    include_blueprint: bool = False,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    G12: Export exam as PDF.

    - include_answers=False → bản học sinh (không đáp án)
    - include_answers=True  → bản giáo viên (có đáp án, explanation, rubric)
    - include_blueprint=True → thêm bảng phân bổ Bloom ở đầu file
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    exporter = ExamExporter(exam_service=service)
    try:
        pdf_bytes = await exporter.export_pdf(
            exam_id=exam_id,
            include_answers=include_answers,
            include_blueprint=include_blueprint,
        )
    except ExamServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    filename = f"{exam.title or 'exam'}_{exam_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get(
    "/{exam_id}/export/docx",
    summary="Export exam as DOCX (G12)",
    description="Generates a Word document (.docx) of the exam. "
                 "**include_answers=False** → bản học sinh. "
                 "**include_answers=True** → bản giáo viên (includes answer key table, "
                 "explanations, and rubric). DOCX is limited to 10MB.",
    responses={
        200: {
            "description": "DOCX file (application/vnd.openxmlformats-officedocument.wordprocessingml.document)",
            "content": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}},
        },
        400: {"description": "DOCX exceeds 10MB limit or exam not found"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
async def export_docx(
    exam_id: UUID,
    include_answers: bool = False,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    G12: Export exam as DOCX.

    - include_answers=False → bản học sinh (không đáp án)
    - include_answers=True  → bản giáo viên (có đáp án, explanation, rubric)
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    exporter = ExamExporter(exam_service=service)
    try:
        docx_bytes = await exporter.export_docx(
            exam_id=exam_id,
            include_answers=include_answers,
        )
    except ExamServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    filename = f"{exam.title or 'exam'}_{exam_id}.docx"
    return StreamingResponse(
        io.BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Content-Length": str(len(docx_bytes)),
        },
    )


@router.get(
    "/{exam_id}/history",
    summary="Get exam history snapshots",
    description="Returns all version snapshots for an exam, "
                 "sorted by version number descending (newest first).",
    responses={
        200: {"description": "List of exam versions (ExamVersion[])"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
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


@router.post(
    "/{exam_id}/history/{history_id}/restore",
    summary="Restore exam to a previous version",
    description="Restores an exam to a specific version snapshot. "
                 "The current version's questions are replaced with the target version's "
                 "questions. A FeedbackEvent with signal_type='restore' is logged.",
    responses={
        200: {"description": "Snapshot restored successfully"},
        400: {"description": "Version not found or restore failed"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam or version not found"},
    },
    tags=["Exams"],
)
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


@router.post(
    "/{exam_id}/approve-blueprint",
    response_model=BlueprintApprovalResponse,
    summary="Approve blueprint — unblock HITL Checkpoint 1",
    description="Called after teacher reviews the blueprint (HITL Checkpoint 1). "
                 "Saves Redis key `hitl:approved:{exam_id}:1` = `true` which unblocks "
                 "the orchestrator's poll loop, allowing the pipeline to proceed "
                 "to question generation. "
                 "WebSocket clients receive the unblock signal via Redis pub/sub.",
    responses={
        200: {"description": "Blueprint approved, pipeline unblocked"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["HITL"],
    example={
        "status": "approved",
        "message": "Blueprint đã được phê duyệt. Bắt đầu sinh câu hỏi.",
    },
)
async def approve_blueprint(
    exam_id: UUID,
    body: BlueprintApprovalRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    HITL Checkpoint 1: Blueprint approval.
    Saves Redis key hitl:approved:{exam_id}:1 to unblock the pipeline.
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    from app.agents.orchestrator import OrchestratorAgent
    orchestrator = OrchestratorAgent(redis=redis, db_session=db)

    await orchestrator.approve_blueprint(
        exam_id=str(exam_id),
        user_id=str(current_user.id),
    )
    return {"status": "approved", "message": "Blueprint đã được phê duyệt. Bắt đầu sinh câu hỏi."}


@router.post(
    "/{exam_id}/reject-blueprint",
    response_model=BlueprintRejectionResponse,
    summary="Reject blueprint and request changes (G8)",
    description="Passes teacher feedback to OutlineAgent as additional instruction. "
                 "OutlineAgent re-generates the blueprint with the feedback, then "
                 "emits a new HITL Checkpoint 1 via WebSocket. "
                 "Also dispatches a Celery task to re-run the full pipeline. "
                 "Use this when the blueprint has incorrect Bloom distribution, "
                 "missing chapters, or wrong question counts.",
    responses={
        200: {"description": "Blueprint rejected, new blueprint emitted"},
        400: {"description": "Feedback too short (< 5 characters)"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["HITL"],
    example={
        "feedback": "Phần Chương 3 chiếm 30% nhưng trong blueprint chỉ có 2 câu. Xin bổ sung thêm câu Vận dụng cao cho Chương 3.",
    },
)
async def reject_blueprint(
    exam_id: UUID,
    request: BlueprintRejectionRequest,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    G8: Re-generate outline with HITL feedback.
    Passes feedback down to Orchestrator which calls OutlineAgent with the feedback
    as additional instruction, then emits a new HITL checkpoint 1.
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    from app.agents.orchestrator import OrchestratorAgent
    orchestrator = OrchestratorAgent(redis=redis, db_session=db)

    result = await orchestrator.reject_blueprint(
        exam_id=str(exam_id),
        user_id=str(current_user.id),
        feedback=request.feedback,
    )
    return result


@router.get(
    "/{exam_id}/review-data",
    response_model=ReviewDataResponse,
    summary="Get full review data for HITL Checkpoint 2",
    description="Returns complete data for the exam review screen: questions, quality_scores "
                 "per question, cost_report from Redis session, feedback_events, "
                 "rejection_history, and exam metadata. "
                 "Call this when the frontend polls for checkpoint 2 status, "
                 "or when navigating to the review screen after inline/prompt edits.",
    responses={
        200: {"description": "Full review data including quality scores and cost report"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["HITL"],
)
async def get_review_data(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    HITL Checkpoint 2: Full data for the review screen.

    Returns exam + questions + quality_scores + cost_report + feedback_events
    so the frontend can display the complete review interface.

    This is called when:
    1. Frontend polls for checkpoint 2 status
    2. User navigates to the review screen
    3. After inline edits or prompt edits to refresh data
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    # Load feedback events
    feedback_events = await service.get_feedback_events(exam_id, current_user.id)
    feedback_dicts = [_feedback_to_dict(f) for f in feedback_events]

    # Load cost report from Redis session
    cost_report: dict = {}
    try:
        session_key = f"session:{exam_id}:{current_user.id}"
        session = await redis.get_json(session_key)
        if session:
            cost_report = session.get("cost_report", {})
    except Exception:
        pass

    # Build per-question quality_scores if available
    questions = exam.questions or []
    quality_scores: list[dict] = []
    for q in questions:
        q_id = q.get("id") or q.get("question_id", "")
        quality_scores.append({
            "question_id": q_id,
            "quality_score": q.get("quality_score"),
            "bloom_level": q.get("bloom_level", ""),
            "difficulty_level": q.get("difficulty_level", ""),
            "is_human_edited": q.get("is_human_edited", False),
            "is_locked": q.get("is_locked", False),
            "is_validated": q.get("is_validated", False),
            "error_categories": q.get("error_categories", []),
            "warnings": q.get("warnings", []),
            "grounding_score": q.get("grounding_score"),
            "verification_status": q.get("verification_status"),
        })

    # Get rejection history from Redis
    rejection_history: list[dict] = []
    try:
        hist_key = f"hitl:rejection_history:{exam_id}"
        raw = await redis.get(hist_key)
        if raw:
            import json
            rejection_history = json.loads(raw)
    except Exception:
        pass

    return {
        "exam_id": str(exam.id),
        "title": exam.title,
        "status": exam.status or "draft",
        "questions": questions,
        "blueprint": exam.blueprint,
        "exam_config": exam.exam_config,
        "quality_scores": quality_scores,
        "cost_report": cost_report,
        "feedback_events": feedback_dicts,
        "rejection_history": rejection_history,
        "instructions": exam.instructions,
        "scope": exam.scope or [],
        "exam_type": exam.exam_type or "mixed",
        "total_questions": exam.total_questions or len(questions),
        "warning_count": exam.warning_count or 0,
        "regenerate_count": exam.regenerate_count or 0,
        "human_edit_count": exam.human_edit_count or 0,
        "version_count": exam.version_count or 1,
    }


@router.get(
    "/{exam_id}/preview",
    response_model=ExportPreviewResponse,
    summary="Get HTML export preview for HITL Checkpoint 3",
    description="Renders the exam as HTML (no PDF conversion). Returns preview_html "
                 "(with current params), student_preview_html (no answers), and "
                 "teacher_preview_html (with answers + rubric). "
                 "Use this before exporting to let the teacher preview the output. "
                 "Query params: include_answers (default False), include_blueprint (default False).",
    responses={
        200: {"description": "HTML preview data (preview_html, student_html, teacher_html)"},
        400: {"description": "Exam has no questions yet — generate first"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["HITL"],
)
async def get_export_preview(
    exam_id: UUID,
    include_answers: bool = False,
    include_blueprint: bool = False,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    HITL Checkpoint 3: HTML preview of the exam export.

    Does NOT call write_pdf() — only renders HTML and returns it as a string.
    Frontend can display this preview inline before user confirms export.

    Query params:
    - include_answers: True = bản giáo viên (có đáp án, explanation, rubric)
    - include_blueprint: True = thêm bảng phân bổ Bloom ở đầu file
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    questions = exam.questions or []
    if not questions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Exam has no questions yet. Generate questions before preview.",
        )

    blueprint = exam.blueprint or {}

    # Use ExamExporter to render HTML (no PDF conversion)
    exporter = ExamExporter(exam_service=service)
    html_content = exporter._render_html(
        exam=exam,
        questions=questions,
        blueprint=blueprint,
        include_answers=include_answers,
        include_blueprint=include_blueprint,
    )

    # Separate preview into student and teacher versions
    student_html = exporter._render_html(
        exam=exam,
        questions=questions,
        blueprint=blueprint,
        include_answers=False,
        include_blueprint=False,
    )

    teacher_html = exporter._render_html(
        exam=exam,
        questions=questions,
        blueprint=blueprint,
        include_answers=True,
        include_blueprint=include_blueprint,
    )

    # Count questions by type
    mcq_count = sum(
        1 for q in questions
        if q.get("type") == "mcq" or q.get("question_type") == "mcq"
    )
    essay_count = sum(
        1 for q in questions
        if q.get("type") == "essay" or q.get("question_type") == "essay"
    )

    return {
        "exam_id": str(exam_id),
        "title": exam.title or "Đề kiểm tra",
        "scope": exam.scope or [],
        "total_questions": len(questions),
        "mcq_count": mcq_count,
        "essay_count": essay_count,
        "preview_html": html_content,
        "student_preview_html": student_html,
        "teacher_preview_html": teacher_html,
        "include_answers": include_answers,
        "include_blueprint": include_blueprint,
        "word_count": len(html_content),
        "estimated_pdf_pages": max(1, (len(questions) // 5) + 2),
    }


@router.post(
    "/{exam_id}/submit-review",
    response_model=ExamReviewResponse,
    summary="Submit exam review — approve or request changes (HITL Checkpoint 2)",
    description="Submit review for the generated exam at HITL Checkpoint 2. "
                 "If approved=True: saves teacher preferences to long-term memory (G14), "
                 "sets `hitl:approved:{exam_id}:2` Redis key, marks exam ready for export. "
                 "If approved=False: dispatches a Celery task to re-generate the exam "
                 "with the provided feedback and optional direct edits.",
    responses={
        200: {"description": "Review submitted successfully"},
        400: {"description": "Review approval failed"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
        422: {"description": "Validation error in request body"},
    },
    tags=["HITL"],
    example={
        "approved": False,
        "feedback": "Câu 3 và câu 7 chưa chính xác, xin điều chỉnh lại nội dung",
    },
)
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
