"""
Guidance Router — Student submission, grading, and guidance endpoints.

Endpoints:
  POST /submissions               — submit answers
  GET  /submissions/{id}          — get submission detail
  POST /submissions/{id}/grade    — auto-grade MCQ
  GET  /submissions/{id}/guidance — get personalized guidance
  GET  /students/{id}/mastery     — get mastery profile

Spec reference: §6.16
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from database import get_db
from models.user import User
from routers.auth import get_current_user
from services.guidance_service import GuidanceService
from services.exam_service import ExamService

router = APIRouter(tags=["guidance"])


# ──────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────

class AnswerPayload(BaseModel):
    question_id: str
    answer: str


class SubmissionCreateRequest(BaseModel):
    exam_id: str
    exam_version_id: Optional[str] = None
    answers: list[AnswerPayload]


class SubmissionResponse(BaseModel):
    id: str
    student_id: str
    exam_id: str
    status: str
    total_score: Optional[float] = None
    max_possible_score: Optional[float] = None
    auto_graded: bool = False
    submitted_at: Optional[str] = None
    graded_at: Optional[str] = None

    model_config = {"from_attributes": True}


class MasteryEntry(BaseModel):
    scope_id: str
    scope_type: str
    scope_title: Optional[str] = None
    overall_mastery: float = 0.0
    bloom_mastery: dict = Field(default_factory=dict)
    total_attempts: int = 0
    correct_count: int = 0
    total_count: int = 0


class GuidanceResponse(BaseModel):
    submission_id: str
    total_score: Optional[float] = None
    max_score: Optional[float] = None
    percentage: Optional[float] = None
    weak_topics: list[dict] = Field(default_factory=list)
    strong_topics: list[dict] = Field(default_factory=list)
    overall_recommendation: str = ""


# ──────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────

@router.post("/submissions", response_model=SubmissionResponse)
async def create_submission(
    request: SubmissionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit student answers for an exam."""
    service = GuidanceService(db)
    submission = await service.create_submission(
        student_id=current_user.id,
        exam_id=request.exam_id,
        answers=[a.model_dump() for a in request.answers],
        exam_version_id=request.exam_version_id,
    )
    return SubmissionResponse(
        id=submission.id,
        student_id=submission.student_id,
        exam_id=submission.exam_id,
        status=submission.status,
        total_score=submission.total_score,
        max_possible_score=submission.max_possible_score,
        auto_graded=submission.auto_graded,
        submitted_at=submission.submitted_at.isoformat() if submission.submitted_at else None,
        graded_at=submission.graded_at.isoformat() if submission.graded_at else None,
    )


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
async def get_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get submission details."""
    service = GuidanceService(db)
    submission = await service.get_submission(submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    # Security: only the student or admin can view
    if submission.student_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    return SubmissionResponse(
        id=submission.id,
        student_id=submission.student_id,
        exam_id=submission.exam_id,
        status=submission.status,
        total_score=submission.total_score,
        max_possible_score=submission.max_possible_score,
        auto_graded=submission.auto_graded,
        submitted_at=submission.submitted_at.isoformat() if submission.submitted_at else None,
        graded_at=submission.graded_at.isoformat() if submission.graded_at else None,
    )


@router.post("/submissions/{submission_id}/grade", response_model=SubmissionResponse)
async def grade_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-grade MCQ questions in a submission."""
    guidance_service = GuidanceService(db)
    exam_service = ExamService(db)

    submission = await guidance_service.get_submission(submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Load exam questions
    exam = await exam_service.get_exam(submission.exam_id, current_user.id)
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")

    # Get active version questions
    questions = []
    version = getattr(exam, "current_version", None)
    if version and version.questions:
        questions = version.questions
    elif hasattr(exam, "versions") and exam.versions:
        latest = max(exam.versions, key=lambda v: v.version_number)
        questions = latest.questions or []

    # Convert to dicts for grading
    question_dicts = []
    for q in questions:
        q_type = q.question_type.value if hasattr(q.question_type, "value") else q.question_type
        bloom = q.bloom_level.value if hasattr(q.bloom_level, "value") else q.bloom_level
        question_dicts.append({
            "id": q.id,
            "question_type": q_type,
            "correct_answer": q.correct_answer,
            "bloom_level": bloom,
            "scope_tags": q.scope_tags_json or [],
        })

    graded = await guidance_service.auto_grade(submission_id, question_dicts)

    # Update mastery profile
    await guidance_service.update_mastery_from_submission(current_user.id, graded)

    return SubmissionResponse(
        id=graded.id,
        student_id=graded.student_id,
        exam_id=graded.exam_id,
        status=graded.status,
        total_score=graded.total_score,
        max_possible_score=graded.max_possible_score,
        auto_graded=graded.auto_graded,
        submitted_at=graded.submitted_at.isoformat() if graded.submitted_at else None,
        graded_at=graded.graded_at.isoformat() if graded.graded_at else None,
    )


@router.get("/submissions/{submission_id}/guidance", response_model=GuidanceResponse)
async def get_guidance(
    submission_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get personalized guidance for a submission."""
    service = GuidanceService(db)
    submission = await service.get_submission(submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    guidance = await service.generate_guidance(submission_id)
    return GuidanceResponse(**guidance)


@router.get("/students/{student_id}/mastery", response_model=list[MasteryEntry])
async def get_mastery_profile(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get mastery profile for a student."""
    # Security: only the student, admin, or lecturer can view
    if current_user.id != student_id and current_user.role not in ("admin", "lecturer"):
        raise HTTPException(status_code=403, detail="Not authorized")

    service = GuidanceService(db)
    profiles = await service.get_mastery_profile(student_id)

    return [
        MasteryEntry(
            scope_id=p.scope_id,
            scope_type=p.scope_type or "chapter",
            scope_title=p.scope_title,
            overall_mastery=p.overall_mastery or 0.0,
            bloom_mastery=p.bloom_mastery_json or {},
            total_attempts=p.total_attempts or 0,
            correct_count=p.correct_count or 0,
            total_count=p.total_count or 0,
        )
        for p in profiles
    ]
