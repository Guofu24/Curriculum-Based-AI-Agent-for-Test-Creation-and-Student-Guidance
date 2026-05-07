"""Exam router: generate, list, detail, edit, export - aligned with frontend API."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
import uuid
import time
from datetime import date

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.core.config import get_settings
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/exams", tags=["Exams"])


# ── Rate limit helper (G13) ───────────────────────────────────────────────────
MAX_GENERATES_PER_DAY = get_settings().MAX_GENERATES_PER_DAY


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
        "current_version_number": len(exam.history) if exam.history else None,
        "version_count": exam.version_count or 1,
        "verifier_pass_rate": float(exam.verifier_pass_rate) if exam.verifier_pass_rate else None,
        "evidence_coverage_rate": float(exam.evidence_coverage_rate) if exam.evidence_coverage_rate else None,
        "warning_count": exam.warning_count or 0,
        "regenerate_count": exam.regenerate_count or 0,
        "human_edit_count": exam.human_edit_count or 0,
        "feedback_event_count": len(exam.feedback_events) if exam.feedback_events is not None else 0,
        "created_at": exam.created_at.isoformat() if exam.created_at else None,
        "updated_at": exam.updated_at.isoformat() if exam.updated_at else None,
    }


def _exam_to_detail(exam, versions=None, feedback_events=None) -> dict:
    """Convert Exam model to dict matching frontend's Exam interface."""
    questions = exam.questions or []
    chapters_str: list[str] = exam.chapters or []
    chapters_num: list[int] = [i + 1 for i in range(len(chapters_str))]

    # Normalize questions: ensure each question has a `type` alias for `question_type`
    normalized_questions = []
    for q in questions:
        if isinstance(q, dict):
            q = dict(q)
            # Alias question_type → type for frontend compatibility
            if "question_type" in q and "type" not in q:
                q["type"] = q["question_type"]
            # Normalize question → content (LLM may use "question" instead of "content")
            if "question" in q and "content" not in q:
                q["content"] = q.pop("question")
            # Normalize answer → correct_answer (LLM may use "answer" instead of "correct_answer")
            if "answer" in q and "correct_answer" not in q:
                q["correct_answer"] = q.pop("answer")
            # Normalize stem → content (if LLM sends stem instead of content)
            if "stem" in q and "content" not in q:
                q["content"] = q.pop("stem")
            # Normalize correct → correct_answer (fallback)
            if "correct" in q and "correct_answer" not in q:
                q["correct_answer"] = q.pop("correct")
            # Normalize warnings → validation_warnings
            if "warnings" in q and "validation_warnings" not in q:
                q["validation_warnings"] = q.get("warnings", [])
            # Normalize MCQ options: backend uses {id, text}, frontend expects {label, text}
            if "options" in q and isinstance(q["options"], list):
                q["options"] = [
                    {"label": str(opt.get("id", opt.get("label", ""))), "text": str(opt.get("text", ""))}
                    if isinstance(opt, dict) else opt
                    for opt in q["options"]
                ]
            normalized_questions.append(q)
        else:
            normalized_questions.append(q)

    # Enrich questions with quality metrics on-the-fly (covers exams saved before enrichment was added)
    from app.services.exam_service import ExamService
    q_list = []
    enriched_normalized = []
    for q in normalized_questions:
        if isinstance(q, dict):
            q = ExamService._enrich_question_metrics(q)
            q_list.append(q)
        enriched_normalized.append(q)
    normalized_questions = enriched_normalized

    # Aggregate quality metrics from enriched questions
    verifier_passed = sum(1 for q in q_list if q.get("is_validated"))
    evidence_covered = sum(
        1 for q in q_list
        if q.get("source_evidence") or q.get("source_citations")
    )
    total_q = len(q_list)
    verifier_pass_rate = round(verifier_passed / total_q, 4) if total_q > 0 else None
    evidence_coverage_rate = round(evidence_covered / total_q, 4) if total_q > 0 else None
    # quality_score: average of per-question scores
    q_scores = [float(q["quality_score"]) for q in q_list if q.get("quality_score") is not None]
    avg_quality_score = round(sum(q_scores) / len(q_scores), 4) if q_scores else None
    all_warnings = [w for q in q_list for w in q.get("warnings", [])]
    warning_count = len(all_warnings)

    # Normalize blueprint: prioritise dedicated column, fallback to exam_config
    raw_blueprint = exam.blueprint
    blueprint_list: list[dict] = []
    if isinstance(raw_blueprint, list):
        blueprint_list = raw_blueprint
    elif isinstance(raw_blueprint, dict) and "slots" in raw_blueprint:
        blueprint_list = raw_blueprint.get("slots", [])
    elif isinstance(raw_blueprint, dict) and "blueprint" in raw_blueprint:
        blueprint_list = raw_blueprint.get("blueprint", [])

    # Fallback: blueprint may have been stored inside exam_config by older pipeline versions
    if not blueprint_list:
        cfg_bp = (exam.exam_config or {}).get("blueprint")
        if isinstance(cfg_bp, list):
            blueprint_list = cfg_bp
        elif isinstance(cfg_bp, dict):
            blueprint_list = cfg_bp.get("slots") or cfg_bp.get("blueprint") or []

    return {
        "id": str(exam.id),
        "title": exam.title,
        "document_id": str(exam.document_id) if exam.document_id else "",
        "course_id": str(exam.course_id) if exam.course_id else None,
        "exam_type": exam.exam_type or "mixed",
        "difficulty": exam.difficulty or "medium",
        "status": exam.status or "draft",
        "chapters": chapters_str,
        "chapters_num": chapters_num,
        "variant_number": exam.variant_number or 1,
        "total_questions": exam.total_questions or len(questions),
        "instructions": exam.instructions,
        "output_language": exam.output_language or "vi",
        "strict_scope_flag": exam.strict_scope_flag if exam.strict_scope_flag is not None else True,
        "quality_score": avg_quality_score if avg_quality_score is not None else (float(exam.quality_score) if exam.quality_score else None),
        "verifier_pass_rate": verifier_pass_rate,
        "evidence_coverage_rate": evidence_coverage_rate,
        "warning_count": warning_count,
        "created_at": exam.created_at.isoformat() if exam.created_at else None,
        "updated_at": exam.updated_at.isoformat() if exam.updated_at else None,
        "published_at": exam.published_at.isoformat() if exam.published_at else None,
        "questions": normalized_questions,
        "exam_spec": exam.exam_spec,
        "blueprint": blueprint_list,
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
    # Map snapshot status to change_type for frontend compatibility
    raw_status = getattr(version, "status", None) or snapshot.get("status") or "draft"
    # Normalize status → change_type for FE
    change_type_map = {
        "draft": "generate",
        "under_review": "generate",
        "published": "published",
        "regenerating": "regenerate",
    }
    change_type = change_type_map.get(str(raw_status), "generate")

    return {
        "id": str(version.id),
        "version_number": getattr(version, "version_number", None) or 1,
        "change_type": change_type,
        "change_description": getattr(version, "change_summary", None) or getattr(version, "change_description", None) or getattr(version, "change_summary", "") or f"Phiên bản {getattr(version, 'version_number', 1)}",
        "created_at": version.created_at.isoformat() if version.created_at else None,
        # Additional fields for full compatibility
        "status": raw_status,
        "created_by": str(getattr(version, "created_by", "") or ""),
        "parent_version_id": str(getattr(version, "parent_version_id", None)) if getattr(version, "parent_version_id", None) else None,
        "questions": getattr(version, "questions", None) or snapshot.get("questions", []),
        "edit_operations": getattr(version, "edit_operations", None) or [],
        "feedback_events": [],
    }


def _feedback_to_dict(event) -> dict:
    """Convert FeedbackEvent to dict matching frontend's FeedbackEvent."""
    if isinstance(event, dict):
        return event

    review_status = getattr(event, "review_status", None) or ""
    resolved = review_status in ("accepted", "rejected", "corrected")

    # Build description from signal_type if not set
    description = getattr(event, "description", None)
    if not description:
        signal_type = getattr(event, "signal_type", "") or ""
        signal_descriptions = {
            "bloom_mismatch": "Bloom level không khớp với nội dung câu hỏi",
            "out_of_scope": "Câu hỏi chứa nội dung ngoài phạm vi tài liệu",
            "duplicate": "Câu hỏi trùng lặp với câu hỏi khác",
            "quality_low": "Chất lượng câu hỏi thấp",
            "answer_incorrect": "Đáp án có thể không chính xác",
            "validation_warning": "Cảnh báo từ bước validation",
            "generation_error": "Lỗi trong quá trình sinh câu hỏi",
            "publish": "Đề thi đã được xuất bản",
            "edit_applied": "Chỉnh sửa đã được áp dụng",
        }
        description = signal_descriptions.get(signal_type, f"Tín hiệu chất lượng: {signal_type}")

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
        "review_status": review_status,
        "reviewed_by_human": getattr(event, "reviewed_by_human", False) or False,
        "question_id": str(getattr(event, "question_id", None)) if getattr(event, "question_id", None) else None,
        "error_categories": getattr(event, "error_categories", None) or [],
        "before_snapshot_ref": getattr(event, "before_snapshot_ref", None),
        "after_snapshot_ref": getattr(event, "after_snapshot_ref", None),
        "linked_eval_sample_id": None,
        "payload": getattr(event, "payload", None),
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "description": description,
        "resolved": resolved,
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

    # Extract section titles from scope strings ("Chương > Phần" → "Phần")
    scope_sections: list[str] = []
    if config.scope and isinstance(config.scope, list):
        for s in config.scope:
            if isinstance(s, str) and " > " in s:
                section_part = s.split(" > ", 1)[1].strip()
                if section_part:
                    scope_sections.append(section_part)

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
            "scope_sections": scope_sections if scope_sections else None,
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
        request_trace_id=job_id,
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
    exams, total = await service.list_exams(
        user_id=current_user.id,
        page=page,
        limit=limit,
        status=status,
    )
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=[_exam_to_list_item(e) for e in exams],
        headers={"total-count": str(total)},
    )


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
    _log = logging.getLogger("exam.router")
    service = ExamService(db, redis)
    result = await service.get_quality_summary(current_user.id)
    _log.debug("quality-summary returned: %s", result)
    return result


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
    signal_type: str | None = None,
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
        signal_type=signal_type,
    )
    return {
        "items": [_feedback_to_dict(f) for f in events],
        "total": total,
        "page": page,
        "limit": limit,
    }


# ── Per-exam endpoints (path params must come AFTER global endpoints) ─────────────

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


@router.post(
    "/{exam_id}/backfill-blueprint",
    summary="Synthesize and save blueprint from existing questions",
    description="For exams that were generated before blueprint persistence was implemented, "
                 "this endpoint synthesizes a blueprint (one slot per question) from the "
                 "existing question data and saves it to the DB. Safe to call multiple times.",
    responses={
        200: {"description": "Blueprint synthesized and saved"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
async def backfill_blueprint(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Synthesize blueprint from questions and save to DB (backfill for older exams)."""
    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    questions = list(exam.questions or [])
    if not questions:
        return {"message": "No questions to synthesize blueprint from", "slots": 0}

    # Check if blueprint already exists as a valid list
    existing = exam.blueprint
    if isinstance(existing, list) and len(existing) > 0:
        return {"message": "Blueprint already exists", "slots": len(existing)}

    # Synthesize one slot per question
    blueprint_slots = [
        {
            "question_id": q.get("id") or q.get("question_id", f"Q_{i + 1}"),
            "type": q.get("type") or q.get("question_type", "mcq"),
            "bloom_level": q.get("bloom_level", "thong_hieu"),
            "chapter": q.get("chapter", ""),
            "topic_hint": q.get("topic_hint", (q.get("content") or q.get("stem") or "")[:60]),
            "estimated_difficulty": float(q.get("estimated_difficulty") or q.get("difficulty_score") or 0.5),
        }
        for i, q in enumerate(questions)
        if isinstance(q, dict)
    ]

    try:
        await service.update_blueprint(exam_id=exam_id, blueprint=blueprint_slots)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return {"message": f"Blueprint synthesized and saved ({len(blueprint_slots)} slots)", "slots": len(blueprint_slots)}


@router.post(
    "/{exam_id}/backfill-quality",
    summary="Recompute quality metrics for existing exam questions",
    description="For exams generated before quality-metric enrichment was implemented, "
                 "this recomputes quality_score, is_validated, and source_evidence "
                 "from question data and saves them to the DB. Safe to call multiple times.",
    responses={
        200: {"description": "Quality metrics recomputed and saved"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["Exams"],
)
async def backfill_quality(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """Recompute and save quality metrics for all questions in an exam."""
    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    updated = await service.recompute_quality_metrics(exam_id)
    return {"message": f"Quality metrics recomputed for {updated} questions", "questions_updated": updated}


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


@router.post(
    "/{exam_id}/partial-regenerate",
    summary="Regenerate a single question with optional prompt (CP2 per-question edit)",
    description="Regenerates one question by question_id using BuilderAgent. "
                "An optional `prompt` lets the teacher specify exactly what to change. "
                "Only that question is re-generated — the rest of the exam is unchanged. "
                "Emits a `question_updated` WebSocket event when done.",
    responses={
        200: {"description": "Updated question object"},
        400: {"description": "question_id not found or generation failed"},
        401: {"description": "Authentication required"},
        404: {"description": "Exam not found"},
    },
    tags=["HITL"],
)
async def partial_regenerate(
    exam_id: UUID,
    request: dict,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    CP2 per-question edit: regenerate one question with an optional prompt.

    Loads retrieved_context and existing questions from the Redis session
    saved at emit_checkpoint_2. Calls BuilderAgent.build_single_question()
    then emits a `question_updated` WebSocket event so the frontend can
    swap only that question in the list without a full reload.
    """
    from pydantic import BaseModel

    class PartialRegenerateRequest(BaseModel):
        question_id: str
        prompt: str = ""

    try:
        req = PartialRegenerateRequest(**request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {e}")

    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    # Load session from Redis (saved at CP2 emit)
    from app.agents.memory.short_term import ShortTermMemory
    stm = ShortTermMemory(redis)
    session = await stm.load_session(str(exam_id), str(current_user.id))

    if not session:
        raise HTTPException(
            status_code=400,
            detail="Session not found — cannot regenerate without context. "
                   "Make sure the exam reached CP2.",
        )

    retrieved_context = session.get("retrieved_context", [])
    existing_questions = session.get("questions", []) or exam.questions or []

    if not any(q.get("question_id") == req.question_id for q in existing_questions):
        raise HTTPException(
            status_code=400,
            detail=f"question_id {req.question_id!r} not found in current questions.",
        )

    # Regenerate the single question
    from app.agents.builder import BuilderAgent
    builder = BuilderAgent(redis_client=redis)
    new_question = await builder.build_single_question(
        question_id=req.question_id,
        retrieved_context=retrieved_context,
        extra_prompt=req.prompt,
        existing_questions=existing_questions,
        trace_id=f"{exam_id}_partial_{req.question_id}",
    )

    if not new_question:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to regenerate question {req.question_id}.",
        )

    # Update question in session
    updated_questions = [
        new_question if q.get("question_id") == req.question_id else q
        for q in existing_questions
    ]
    session["questions"] = updated_questions
    session_key = stm._session_key(str(exam_id), str(current_user.id))
    await redis.set_json(session_key, session, ttl=7200)

    # Persist updated question to DB
    try:
        await service.update_question(
            exam_id, req.question_id, new_question, current_user.id
        )
    except Exception:
        pass  # Non-critical — WS event still fired

    # Emit question_updated WebSocket event
    try:
        from app.websocket.manager import get_connection_manager
        from app.agents.graph.nodes._emit import _emit_async
        manager = get_connection_manager()
        await _emit_async(manager, str(exam_id), {
            "type": "question_updated",
            "question_id": req.question_id,
            "question": new_question,
        })
    except Exception as ws_err:
        logger.warning("Failed to emit question_updated for exam %s: %s", exam_id, ws_err)

    return {"question": new_question, "question_id": req.question_id}




# ── Export PDF / DOCX ───────────────────────────────────────────────────────────

@router.get(
    "/{exam_id}/export/pdf",
    summary="Export exam as PDF (G12)",
    description="Generates a PDF file of the exam using ReportLab. "
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

    Saves approval state in Redis key, then resumes the paused LangGraph via
    Command(resume={...}) so the pipeline continues to build_questions.
    The graph was paused at wait_for_blueprint_approval via interrupt().
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    # Save approval in Redis (belt-and-suspenders for crash recovery)
    key = f"hitl:approved:{exam_id}:1"
    try:
        await redis.set(key, "true", ttl=3600)
    except Exception as exc:
        logger.warning("Failed to save HITL approval to Redis (key=%s): %s", key, exc)

    # Resume the interrupted graph via Command(resume=...)
    # If no interrupt is found (graph already completed), this logs a warning but doesn't fail.
    try:
        from langgraph.types import Command
        from app.agents.graph.builder import build_exam_graph
        graph = build_exam_graph()
        config = {
            "configurable": {"thread_id": str(exam_id)},
            "recursion_limit": 500,
        }
        logger.info(f"Resuming graph for exam {exam_id} with Command(resume={{approved: True}})")
        await graph.ainvoke(
            Command(resume={"approved": True}),
            config=config,
        )
    except Exception as e:
        if "interrupt" in str(e).lower() or "nothing to resume" in str(e).lower():
            logger.info(f"No interrupt to resume for exam {exam_id}: {e}")
        else:
            logger.warning(f"Could not resume graph for exam {exam_id}: {e}")

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
    G8: Reject blueprint with feedback and resume graph.
    Stores rejection + feedback in Redis, then resumes the interrupted graph
    via Command(resume={...}). The graph's wait_for_blueprint_approval node
    receives approved=False and routes to create_outline with the feedback.
    """
    service = ExamService(db, redis)

    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    # Store rejection + feedback in Redis so the graph node can retrieve it
    import json
    rejection_key = f"hitl:rejected:{exam_id}:1"
    try:
        await redis.set(rejection_key, json.dumps({
            "feedback": request.feedback,
            "user_id": str(current_user.id),
            "timestamp": time.time(),
        }), ttl=3600)
    except Exception:
        pass

    # Resume the interrupted graph with rejection signal
    try:
        from langgraph.types import Command
        from app.agents.graph.builder import build_exam_graph
        graph = build_exam_graph()
        config = {
            "configurable": {"thread_id": str(exam_id)},
            "recursion_limit": 500,
        }
        logger.info(f"Resuming graph for exam {exam_id} with Command(resume={{approved: False}})")
        await graph.ainvoke(
            Command(resume={"approved": False, "feedback": request.feedback}),
            config=config,
        )
    except Exception as e:
        if "interrupt" in str(e).lower() or "nothing to resume" in str(e).lower():
            logger.info(f"No interrupt to resume for exam {exam_id}: {e}")
            # Fallback: dispatch Celery task to re-run the pipeline from scratch
            from app.tasks.exam_task import generate_exam_task
            session_key = f"session:{exam_id}:{current_user.id}"
            try:
                session = await redis.get_json(session_key)
            except Exception as exc:
                logger.warning("Failed to load session from Redis for exam %s: %s", exam_id, exc)
                session = None
            generate_exam_task.delay(
                exam_id=str(exam_id),
                user_id=str(current_user.id),
                document_id=session.get("document_id") if session else None,
                scope=session.get("scope", []) if session else [],
                exam_config={**(session.get("exam_config_original", {}) if session else {}), "outline_feedback": request.feedback},
                user_prompt=session.get("exam_config_original", {}).get("user_prompt", "") if session else "",
                extra_instructions=request.feedback,
            )
        else:
            logger.warning(f"Could not resume graph for exam {exam_id}: {e}")

    return {
        "status": "rejected_with_feedback",
        "message": f"Đã ghi nhận phản hồi. Blueprint sẽ được điều chỉnh: {request.feedback[:50]}...",
    }


@router.post(
    "/{exam_id}/clarify",
    summary="Submit clarification answers and resume pipeline",
    description="Receives answers to clarification questions, merges them into user_prompt, "
                "and resumes the paused LangGraph pipeline so generation can continue.",
    tags=["HITL"],
)
async def submit_clarification(
    exam_id: UUID,
    request: dict,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """
    Resume pipeline after clarification answers are provided.

    Merges answers_text into exam_config.user_prompt and resumes
    the interrupted LangGraph graph via Command(resume=...).
    Falls back to restarting the Celery task if no active interrupt.
    """
    import json as _json

    service = ExamService(db, redis)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exam not found")

    answers_text: str = request.get("answers_text", "")
    answers: dict = request.get("answers", {})

    # Retrieve original session config from Redis to merge answers into user_prompt
    session_key = f"session:{exam_id}:{current_user.id}"
    try:
        session = await redis.get_json(session_key)
    except Exception:
        session = {}

    exam_config_orig: dict = (session or {}).get("exam_config_original", {}) if session else {}
    original_prompt: str = exam_config_orig.get("user_prompt", "")
    merged_prompt = f"{original_prompt}\n\n[Làm rõ yêu cầu]\n{answers_text}".strip()
    exam_config_orig = {**exam_config_orig, "user_prompt": merged_prompt}

    # Store updated answers in Redis for the graph to pick up
    clarify_key = f"clarification:{exam_id}"
    try:
        await redis.set(clarify_key, _json.dumps({
            "answers": answers,
            "answers_text": answers_text,
            "merged_prompt": merged_prompt,
        }), ttl=3600)
    except Exception:
        pass

    # Try to resume interrupted graph first
    try:
        from langgraph.types import Command
        from app.agents.graph.builder import build_exam_graph
        graph = build_exam_graph()
        config = {
            "configurable": {"thread_id": str(exam_id)},
            "recursion_limit": 500,
        }
        logger.info(f"[clarify] Resuming graph for exam {exam_id} with clarification answers")
        await graph.ainvoke(
            Command(resume={"clarification_answers": answers, "merged_prompt": merged_prompt}),
            config=config,
        )
    except Exception as e:
        if "interrupt" in str(e).lower() or "nothing to resume" in str(e).lower():
            # No active interrupt — restart the pipeline with the merged prompt
            logger.info(f"[clarify] No interrupt for {exam_id}, restarting pipeline: {e}")
            generate_exam_task.delay(
                exam_id=str(exam_id),
                user_id=str(current_user.id),
                document_id=(session or {}).get("document_id") if session else None,
                scope=(session or {}).get("scope", []) if session else [],
                exam_config={**exam_config_orig},
                user_prompt=merged_prompt,
                extra_instructions=(session or {}).get("extra_instructions", "") if session else "",
            )
        else:
            logger.warning(f"[clarify] Could not resume graph for {exam_id}: {e}")

    return {
        "status": "clarification_submitted",
        "message": "Đã nhận câu trả lời, đang tiếp tục tạo đề...",
        "merged_prompt_preview": merged_prompt[:120],
    }


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

    # Normalize questions for frontend compatibility
    normalized_questions: list[dict] = []
    for q in questions:
        if isinstance(q, dict):
            q = dict(q)
            if "question_type" in q and "type" not in q:
                q["type"] = q["question_type"]
            # Normalize question → content (LLM may use "question" instead of "content")
            if "question" in q and "content" not in q:
                q["content"] = q.pop("question")
            # Normalize answer → correct_answer (LLM may use "answer" instead of "correct_answer")
            if "answer" in q and "correct_answer" not in q:
                q["correct_answer"] = q.pop("answer")
            # Normalize stem → content (if LLM sends stem instead of content)
            if "stem" in q and "content" not in q:
                q["content"] = q.pop("stem")
            # Normalize correct → correct_answer (fallback)
            if "correct" in q and "correct_answer" not in q:
                q["correct_answer"] = q.pop("correct")
            if "warnings" in q and "validation_warnings" not in q:
                q["validation_warnings"] = q.get("warnings", [])
            # Normalize MCQ options: backend uses {id, text}, frontend expects {label, text}
            if "options" in q and isinstance(q["options"], list):
                q["options"] = [
                    {"label": str(opt.get("id", opt.get("label", ""))), "text": str(opt.get("text", ""))}
                    if isinstance(opt, dict) else opt
                    for opt in q["options"]
                ]
            normalized_questions.append(q)
        else:
            normalized_questions.append(q)

    # Normalize blueprint: dict → list
    raw_blueprint = exam.blueprint
    if isinstance(raw_blueprint, list):
        blueprint_list = raw_blueprint
    elif isinstance(raw_blueprint, dict):
        blueprint_list = raw_blueprint.get("slots", []) or raw_blueprint.get("blueprint", [])
    else:
        blueprint_list = []

    return {
        "exam_id": str(exam.id),
        "title": exam.title,
        "status": exam.status or "draft",
        "questions": normalized_questions,
        "blueprint": blueprint_list,
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

    # orchestrator.submit_review may return {'status': 'failed', 'error': '...'}
    # instead of a valid ExamReviewResponse dict — convert to proper HTTP error.
    if isinstance(result, dict) and result.get("status") == "failed":
        error_msg = result.get("error", "Review submission failed")
        if "session not found" in error_msg.lower() or "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Exam session expired or not found. Please start a new generation. ({error_msg})",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg,
        )

    # Ensure result always has required fields for ExamReviewResponse
    if isinstance(result, dict) and "message" not in result:
        result["message"] = "Review submitted successfully."

    return result

