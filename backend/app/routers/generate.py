"""Generation router — FE-compatible endpoints aligned with ui/lib/api.ts.

Bridges the gap between the FE's ExamGenerationRequest shape and the backend's
ExamConfigRequest / Celery-based generation pipeline.

Key alignments:
- POST /generate/exam: FE-compatible generation trigger (maps to /exams/generate)
- SSE /generate/exam/stream: replaced with WebSocket (see /ws/exam/{exam_id})
- POST /generate/partial-regenerate: maps to /exams/{id}/questions/{id} PATCH
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.core.config import get_settings
from app.schemas.exam import ExamConfigRequest, ExamGenerateResponse
from app.dependencies import get_current_user
from app.models.user import User
import uuid

router = APIRouter(prefix="/api/v1/generate", tags=["Generation"])


# ── Inline generation (shares FastAPI's async event loop — no loop conflicts) ──

async def _run_generation_inline(
    exam_id: str | None,
    user_id: str | None,
    document_id: str | None,
    scope: list | None,
    exam_config: dict | None,
    user_prompt: str | None,
    extra_instructions: str | None,
) -> dict:
    """
    Generation logic that runs directly in FastAPI's async event loop.
    Does NOT create a ThreadPoolExecutor — avoids Redis/WebSocket loop conflicts.
    """
    import asyncio
    import logging as _log
    from app.core.database import async_session_maker
    from app.core.redis_client import get_redis_client
    from app.services.exam_service import ExamService
    from app.websocket.manager import get_connection_manager, SSEvent
    from app.core.config import get_settings

    settings = get_settings()
    _logger = _log.getLogger("generate.inline")

    async with async_session_maker() as db:
        redis_client = get_redis_client()
        manager = get_connection_manager()

        trace_meta = {
            "user_id": user_id,
            "document_id": document_id,
            "scope": scope,
            "bloom_distribution": (exam_config or {}).get("bloom_distribution"),
            "demo_mode": settings.DEMO_MODE or not document_id,
        }

        async def stream_callback(event: dict):
            channel = exam_id
            if channel:
                await manager.emit(channel, event)

        await manager.emit(
            exam_id or "",
            SSEvent.plan_step("Bat dau sinh de...", 0, 5),
        )

        use_demo_mode = settings.DEMO_MODE or not document_id
        if use_demo_mode:
            await manager.emit(
                exam_id or "",
                SSEvent.plan_step("Dang tao de demo local...", 1, 5),
            )
            result = _build_demo_payload(exam_id, scope, exam_config, user_prompt)
            for question in result["questions"]:
                await manager.emit(
                    exam_id or "",
                    SSEvent.question_generated(
                        question_id=question.get("question_id", ""),
                        question=question,
                    ),
                )
            await manager.emit(
                exam_id or "",
                SSEvent.validation_result(passed=True, issues_count=0, issues=[]),
            )
            await manager.emit(
                exam_id or "",
                SSEvent.hitl_checkpoint(
                    checkpoint_id=2,
                    data={
                        "exam_id": exam_id,
                        "questions": result["questions"],
                        "validation_passed": True,
                        "issues": [],
                        "warnings": result["warnings"],
                    },
                ),
            )
            await manager.emit(
                exam_id or "",
                SSEvent.hitl_checkpoint(
                    checkpoint_id=3,
                    data={
                        "exam_id": exam_id,
                        "questions": result["questions"],
                        "cost_report": result["cost_report"],
                    },
                ),
            )
        else:
            from app.agents.orchestrator import OrchestratorAgent

            orchestrator = OrchestratorAgent(redis=redis_client, db_session=db)
            orchestrator.set_stream_callback(stream_callback)
            result = await orchestrator.generate_exam(
                exam_id=exam_id,
                user_id=user_id,
                exam_config=exam_config or {},
                user_prompt=user_prompt or "",
                extra_instructions=extra_instructions or "",
                document_id=document_id,
            )

        if exam_id:
            exam_service = ExamService(db, redis_client)
            await exam_service.update_questions(
                exam_id=uuid.UUID(exam_id),
                questions=result.get("questions", []),
                cost_report=result.get("cost_report"),
            )

            status_val = result.get("status")
            is_success = (
                status_val == "success"
                or (hasattr(status_val, "value") and status_val.value == "success")
            )
            if is_success:
                await manager.emit(
                    exam_id,
                    SSEvent.completed(
                        exam_id,
                        total_cost_usd=result.get("cost_report", {}).get("total_cost_usd"),
                    ),
                )
            else:
                await manager.emit(
                    exam_id,
                    SSEvent.error("Exam generation completed with warnings", "orchestrator"),
                )

        return {
            "exam_id": exam_id,
            "status": str(result.get("status", "unknown")),
        }


def _map_fe_to_be_request(data: dict) -> ExamConfigRequest:
    """
    Map frontend ExamGenerationRequest fields to backend ExamConfigRequest.

    FE uses camelCase/snake_mix: document_id, question_distribution,
    output_language, bloom_distribution, formatting_preferences.
    BE uses: document_id, bloom_distribution, output_language.
    """
    scope = data.get("scope", [])
    scope_items = len(scope) if isinstance(scope, list) else 0

    if isinstance(scope, list) and scope and isinstance(scope[0], dict):
        scope = [s.get("title") or s.get("scope_type", "") for s in scope if isinstance(s, dict)]

    # document_id: keep as string (ExamConfigRequest expects str | None)
    doc_id: str | None = data.get("document_id") or None
    if doc_id and not isinstance(doc_id, str):
        doc_id = None

    bloom = data.get("bloom_distribution")
    if bloom is None:
        # Default bloom distribution: 25% each = 100%
        bloom = {
            "nhan_biet": 25,
            "thong_hieu": 25,
            "van_dung": 25,
            "van_dung_cao": 25,
        }

    # Map question_type from FE naming conventions to BE counts
    # FE sends: "mcq_single_answer", "mcq_multiple_answer", "essay", "mixed"
    mcq_count = 0
    essay_count = 0
    qt = data.get("question_type", "")
    total_q = data.get("total_questions", 10)
    if qt in ("mcq_single_answer", "mcq_multiple_answer", "mcq"):
        mcq_count = total_q
    elif qt == "essay":
        essay_count = total_q
    elif qt == "mixed" or qt == "":
        mcq_count = total_q
        essay_count = max(total_q // 5, 2)

    from app.schemas.exam import BloomDistribution
    return ExamConfigRequest(
        document_id=doc_id,
        title=data.get("prompt", "")[:200] if data.get("prompt") else None,
        scope=scope,
        exam_type=data.get("exam_type", "mixed") or "mixed",
        mcq_count=mcq_count,
        essay_count=essay_count,
        bloom_distribution=BloomDistribution(**bloom),
        user_prompt=data.get("prompt") or None,
        extra_instructions=data.get("instructions"),
    )


@router.post(
    "/exam",
    response_model=ExamGenerateResponse,
    summary="Generate exam (FE-compatible, runs synchronously)",
    description="FE calls this at POST /api/v1/generate/exam (matching ui/lib/api.ts). "
                 "Runs the generation pipeline synchronously — no Celery worker needed. "
                 "Returns websocket_url for real-time progress via WebSocket /ws/exam/{exam_id}.",
)
async def generate_exam_fe(
    data: dict,
    db: AsyncSession = Depends(get_db),
    redis: RedisClient = Depends(get_redis_client),
    current_user: User = Depends(get_current_user),
):
    """FE-compatible generation — runs synchronously, no Celery required."""
    import logging
    _log = logging.getLogger("generate.exam")
    from app.services.exam_service import ExamService, ExamServiceError

    try:
        config = _map_fe_to_be_request(data)
    except Exception as e:
        _log.warning("Request mapping failed: %s | input: %s", e, data)
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

    # Rate limit check
    from app.routers.exams import check_generate_rate_limit
    await check_generate_rate_limit(redis, str(current_user.id))

    service = ExamService(db, redis)
    try:
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
    except Exception as e:
        _log.exception("create_exam failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create exam: {e}")

    job_id = str(uuid.uuid4())
    _log.info("Starting generation: exam_id=%s, job_id=%s", exam.id, job_id)

    # Run generation inline — shares the request's async event loop (no loop conflict)
    try:
        result = await _run_generation_inline(
            exam_id=str(exam.id),
            user_id=str(current_user.id),
            document_id=str(config.document_id) if config.document_id else None,
            scope=config.scope,
            exam_config=exam.exam_config,
            user_prompt=config.user_prompt,
            extra_instructions=config.extra_instructions,
        )
    except TimeoutError:
        _log.error("Generation timed out after 120s for exam_id=%s", exam.id)
        raise HTTPException(status_code=504, detail="Generation timed out.")
    except Exception as task_err:
        _log.exception("Generation failed for exam_id=%s: %s", exam.id, task_err)
        raise HTTPException(status_code=500, detail=f"Generation failed: {task_err}")

    _log.info("Generation completed for exam_id=%s", exam.id)
    return ExamGenerateResponse(
        exam_id=str(exam.id),
        job_id=job_id,
        message="Exam generated successfully.",
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
    from uuid import UUID as PyUUID
    from app.services.exam_service import ExamService, ExamServiceError

    exam_id_raw = data.get("exam_id")
    edits = data.get("edits", [])
    if not exam_id_raw:
        raise HTTPException(status_code=422, detail="exam_id is required")

    # Validate exam_id is a valid UUID
    try:
        exam_id = PyUUID(str(exam_id_raw))
    except (ValueError, AttributeError, TypeError) as e:
        raise HTTPException(
            status_code=422,
            detail=f"exam_id must be a valid UUID, got: {exam_id_raw!r} - {e}"
        )

    service = ExamService(db, redis)

    try:
        result = await service.partial_regenerate(
            exam_id=exam_id,
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
