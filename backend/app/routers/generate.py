"""Generation router — FE-compatible endpoints aligned with ui/lib/api.ts.

Bridges the gap between the FE's ExamGenerationRequest shape and the backend's
ExamConfigRequest / Celery-based generation pipeline.

Key alignments:
- POST /generate/exam: FE-compatible generation trigger (maps to /exams/generate)
- SSE /generate/exam/stream: replaced with WebSocket (see /ws/exam/{exam_id})
- POST /generate/partial-regenerate: maps to /exams/{id}/questions/{id} PATCH
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.core.config import get_settings
from app.schemas.exam import ExamConfigRequest, ExamGenerateResponse
from app.dependencies import get_current_user
from app.models.user import User
from app.tasks.exam_task import generate_exam_task
import uuid
import json
import asyncio

router = APIRouter(prefix="/api/v1/generate", tags=["Generation"])


def _map_fe_to_be_request(data: dict) -> ExamConfigRequest:
    """
    Map frontend ExamGenerationRequest fields to backend ExamConfigRequest.

    FE uses camelCase/snake_mix: document_id, question_distribution,
    output_language, bloom_distribution, formatting_preferences.
    BE uses: document_id, bloom_distribution, output_language.
    """
    scope = data.get("scope", [])
    if isinstance(scope, list) and scope and isinstance(scope[0], dict):
        scope = [s.get("title") or s.get("scope_type", "") for s in scope if isinstance(s, dict)]

    bloom = data.get("bloom_distribution")
    if bloom is None:
        qd = data.get("question_distribution", {})
        mcq_dist = qd.get("mcq", {})
        total = data.get("total_questions", 0)
        bloom = {
            "nhan_biet": int(mcq_dist.get("easy", 0) * total / 100) if total else 20,
            "thong_hieu": int(mcq_dist.get("medium", 0) * total / 100) if total else 30,
            "van_dung": int((100 - mcq_dist.get("easy", 20) - mcq_dist.get("medium", 30)) * total / 100) if total else 30,
            "van_dung_cao": 0,
        }

    mcq_count = 0
    essay_count = 0
    qt = data.get("question_type", "")
    total_q = data.get("total_questions", 0)
    if qt in ("mcq", "mixed", ""):
        mcq_count = total_q
    if qt in ("essay", "mixed", ""):
        essay_count = total_q // 5 if total_q else 2

    from app.schemas.exam import BloomDistribution
    return ExamConfigRequest(
        document_id=UUID(data["document_id"]) if data.get("document_id") else None,
        title=data.get("prompt", "")[:200] if data.get("prompt") else None,
        scope=scope,
        exam_type=data.get("exam_type", "mixed") or "mixed",
        mcq_count=mcq_count,
        essay_count=essay_count,
        bloom_distribution=BloomDistribution(**bloom),
        user_prompt=data.get("prompt", ""),
        extra_instructions=data.get("instructions"),
    )


@router.post(
    "/exam",
    response_model=ExamGenerateResponse,
    summary="Start exam generation (FE-compatible endpoint)",
    description="FE calls this at POST /api/v1/generate/exam (matching ui/lib/api.ts). "
                 "Internally dispatches to /exams/generate flow. "
                 "Returns websocket_url for real-time progress via WebSocket /ws/exam/{exam_id}.",
)
async def generate_exam_fe(
    data: dict,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """FE-compatible generation trigger — maps ExamGenerationRequest to ExamConfigRequest."""
    from app.services.exam_service import ExamService, ExamServiceError

    try:
        config = _map_fe_to_be_request(data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid generation request: {e}")

    settings = get_settings()

    # Validate bloom
    bloom = config.bloom_distribution
    total = bloom.nhan_biet + bloom.thong_hieu + bloom.van_dung + bloom.van_dung_cao
    if total != 100:
        raise HTTPException(
            status_code=400,
            detail=f"Bloom distribution must sum to 100%, got {total}%",
        )

    # Rate limit check (G13)
    from app.routers.exams import check_generate_rate_limit
    await check_generate_rate_limit(redis, str(current_user.id))

    service = ExamService(db, redis)
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
        document_id=str(config.document_id) if config.document_id else "",
        scope=config.scope,
        exam_config=exam.exam_config,
        user_prompt=config.user_prompt,
        extra_instructions=config.extra_instructions,
    )

    return ExamGenerateResponse(
        exam_id=exam.id,
        job_id=job_id,
        message="Exam generation started.",
        websocket_url=f"{settings.ws_base_url}/ws/exam/{exam.id}",
    )


@router.post(
    "/partial-regenerate",
    summary="Partial regeneration (FE-compatible)",
    description="FE calls POST /api/v1/generate/partial-regenerate. "
                 "Maps to individual question updates via PATCH /exams/{id}/questions/{id}.",
)
async def partial_regenerate_fe(
    data: dict,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """FE-compatible partial regeneration."""
    from app.services.exam_service import ExamService, ExamServiceError

    exam_id = data.get("exam_id")
    edits = data.get("edits", [])
    if not exam_id:
        raise HTTPException(status_code=422, detail="exam_id is required")

    service = ExamService(db, redis)

    try:
        result = await service.partial_regenerate(
            exam_id=UUID(exam_id),
            edits=edits,
            user_id=current_user.id,
        )
        return result
    except ExamServiceError as e:
        error_msg = str(e)
        if "Access denied" in error_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)


# ── SSE Endpoint (deprecated — replaced by WebSocket /ws/exam/{exam_id}) ───────
# NOTE: Kept for reference only. The FE should use WebSocket via websocket_url
# returned from POST /generate/exam. The WebSocket connection provides real-time
# events: plan_step, question_generated, hitl_checkpoint, completed, error.
#
# FE WebSocket usage:
#   const ws = new WebSocket(websocketUrl);
#   ws.onmessage = (event) => {
#     const data = JSON.parse(event.data);
#     switch(data.type) {
#       case 'plan_step': handlePlanStep(data); break;
#       case 'question_generated': handleQuestion(data.question); break;
#       case 'hitl_checkpoint': handleHITL(data); break;
#       case 'completed': handleCompleted(data); break;
#       case 'error': handleError(data); break;
#     }
#   };
