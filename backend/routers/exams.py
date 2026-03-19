"""
Exams Router

Handles exam CRUD operations, quality summary, feedback inspection, and publishing.
Generation and review edits live under the generation router.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User, UserRole
from routers.auth import get_current_user
from routers.exam_serializers import format_exam, format_exam_list, format_feedback_event, format_version
from schemas.exam import (
    ExamListResponse,
    ExamResponse,
    ExamVersionResponse,
    FeedbackStoreSummaryResponse,
    FeedbackEventResponse,
    QualitySummaryResponse,
)
from services.analytics.quality_summary_service import QualitySummaryService
from services.exam_service import ExamService
from services.feedback.store_service import FeedbackStoreService
from utils.security import require_roles

router = APIRouter(prefix="/exams", tags=["exams"])


@router.get("/", response_model=list[ExamListResponse])
async def list_exams(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ExamService(db)
    exams = await service.get_exams(current_user.id)
    return [format_exam_list(exam) for exam in exams]


@router.get("/quality-summary", response_model=QualitySummaryResponse)
async def get_quality_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = await QualitySummaryService(db).build_summary(current_user.id)
    payload["recent_warnings"] = [format_feedback_event(event) for event in payload["recent_warnings"]]
    return payload


@router.get("/feedback-summary", response_model=FeedbackStoreSummaryResponse)
async def get_feedback_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = await FeedbackStoreService(db).build_summary(user_id=current_user.id)
    payload["recent_events"] = [format_feedback_event(event) for event in payload["recent_events"]]
    return payload


@router.get("/feedback-store", response_model=list[FeedbackEventResponse])
async def get_feedback_store(
    exam_version_id: str | None = Query(default=None),
    question_id: str | None = Query(default=None),
    signal_type: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    event_stage: str | None = Query(default=None),
    error_category: str | None = Query(default=None),
    linked_eval_sample_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    events = await FeedbackStoreService(db).list_events(
        user_id=current_user.id,
        exam_version_id=exam_version_id,
        question_id=question_id,
        signal_type=signal_type,
        review_status=review_status,
        actor_id=actor_id,
        event_stage=event_stage,
        error_category=error_category,
        linked_eval_sample_id=linked_eval_sample_id,
        limit=limit,
    )
    return [format_feedback_event(event) for event in events]


@router.get("/{exam_id}/feedback", response_model=list[FeedbackEventResponse])
async def get_exam_feedback(
    exam_id: str,
    exam_version_id: str | None = Query(default=None),
    question_id: str | None = Query(default=None),
    signal_type: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    event_stage: str | None = Query(default=None),
    error_category: str | None = Query(default=None),
    linked_eval_sample_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        events = await QualitySummaryService(db).get_feedback_events(
            user_id=current_user.id,
            exam_id=exam_id,
            exam_version_id=exam_version_id,
            question_id=question_id,
            signal_type=signal_type,
            review_status=review_status,
            actor_id=actor_id,
            event_stage=event_stage,
            error_category=error_category,
            linked_eval_sample_id=linked_eval_sample_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return [format_feedback_event(event) for event in events]


@router.get("/{exam_id}", response_model=ExamResponse)
async def get_exam(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ExamService(db)
    exam = await service.get_exam(exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return format_exam(exam)


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
    return [format_version(version) for version in versions]


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
    return format_exam(exam)


@router.delete("/{exam_id}")
async def delete_exam(
    exam_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.LECTURER, UserRole.TEACHING_ASSISTANT)),
):
    service = ExamService(db)
    deleted = await service.delete_exam(exam_id, current_user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Exam not found")
    return {"message": "Exam deleted successfully"}
