"""Generation router — FE-compatible endpoints aligned with ui/lib/api.ts.

Bridges the gap between the FE's ExamGenerationRequest shape and the backend's
ExamConfigRequest / Celery-based generation pipeline.

Key alignments:
- POST /generate/exam: FE-compatible generation trigger (maps to /exams/generate)
- SSE /generate/exam/stream: replaced with WebSocket (see /ws/exam/{exam_id})
- POST /generate/partial-regenerate: maps to /exams/{id}/questions/{id} PATCH
"""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis_client import get_redis_client, RedisClient
from app.core.config import get_settings
from app.schemas.exam import ExamConfigRequest, ExamGenerateResponse
from app.dependencies import get_current_user
from app.models.user import User
from app.routers.exams import check_generate_rate_limit
from app.tasks.exam_task import _build_demo_payload
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

        # ── Resolve scope strings → canonical chapter_ids ──────────────────────────
        # Frontend sends "A.QUANG HÌNH HỌC" but chunks have chapter_id="ch1".
        # Normalize scope by looking up heading_tree from the document.
        normalized_scope: list[str] = []
        if document_id and scope and isinstance(scope, list) and scope and isinstance(scope[0], str):
            try:
                from sqlalchemy import select
                from app.models.document import Document
                from app.rag.structure import normalize_chapter_id
                result = await db.execute(
                    select(Document).where(Document.id == UUID(document_id))
                )
                doc = result.scalar_one_or_none()
                if doc and doc.heading_tree:
                    # Build title→chapter_id lookup (case-insensitive, diacritic-insensitive)
                    from app.rag.structure import flatten_heading_tree
                    import unicodedata
                    flat = flatten_heading_tree(doc.heading_tree)
                    title_to_id: dict[str, str] = {}
                    for node in flat:
                        raw_title = node.get("title", "").strip()
                        if not raw_title or not node.get("chapter_id"):
                            continue
                        # Normalize: lowercase + strip diacritics for reliable matching
                        norm = unicodedata.normalize("NFD", raw_title.lower())
                        ascii_key = "".join(c for c in norm if unicodedata.category(c) != "Mn")
                        title_to_id[ascii_key] = node["chapter_id"]

                    for s in scope:
                        if not s:
                            continue
                        # Normalize input the same way
                        norm_s = unicodedata.normalize("NFD", s.strip().lower())
                        ascii_key = "".join(c for c in norm_s if unicodedata.category(c) != "Mn")
                        if ascii_key in title_to_id:
                            normalized_scope.append(title_to_id[ascii_key])
                        else:
                            # Try normalize_chapter_id as fallback
                            resolved = normalize_chapter_id(s)
                            normalized_scope.append(resolved)
                    _logger.info("Scope normalized: %s → %s", scope, normalized_scope)
                else:
                    normalized_scope = [normalize_chapter_id(s) for s in scope if s]
            except Exception as e:
                _logger.warning("Scope normalization failed, using raw scope: %s", e)
                normalized_scope = [normalize_chapter_id(s) for s in (scope or []) if s]
        elif scope and isinstance(scope, list):
            # Already list of dicts or non-strings — pass through
            normalized_scope = scope  # type: ignore[assignment]
        else:
            normalized_scope = scope or []

        trace_meta = {
            "user_id": user_id,
            "document_id": document_id,
            "scope": normalized_scope,  # resolved to canonical chapter_ids
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

            # Inject resolved scope into exam_config so orchestrator uses canonical chapter_ids
            resolved_config = dict(exam_config or {})
            resolved_config["scope"] = normalized_scope

            # Extract section titles from scope strings ("Chương > Phần" → "Phần")
            if scope and isinstance(scope, list):
                section_titles: list[str] = []
                for s in scope:
                    if isinstance(s, str) and " > " in s:
                        section_part = s.split(" > ", 1)[1].strip()
                        if section_part:
                            section_titles.append(section_part)
                if section_titles:
                    resolved_config["scope_sections"] = section_titles
                    logger.info("Extracted scope_sections: %s", section_titles)

            orchestrator = OrchestratorAgent(redis=redis_client, db_session=db)
            orchestrator.set_stream_callback(stream_callback)
            result = await orchestrator.generate_exam(
                exam_id=exam_id,
                user_id=user_id,
                exam_config=resolved_config,
                user_prompt=user_prompt or "",
                extra_instructions=extra_instructions or "",
                document_id=document_id,
            )

        generated_questions = result.get("questions", [])
        status_val = result.get("status")
        is_paused = result.get("pipeline_paused")
        is_success = str(status_val) in ("success", "partial")

        # Pipeline paused at HITL checkpoint — interrupt fired, checkpoint events were
        # already emitted by the graph. Just return; frontend shows the approval UI.
        if is_paused:
            return {
                "exam_id": exam_id,
                "status": str(status_val or "unknown"),
            }

        if not generated_questions:
            await manager.emit(
                exam_id or "",
                SSEvent.error(
                    f"Khong tao duoc cau hoi nao (status={status_val}). "
                    "Nguyen nhan: retrieval tra ve 0 chunks — kiem tra scope/chapter_id.",
                    "orchestrator",
                ),
            )
            return {
                "exam_id": exam_id,
                "status": status_val or "partial",
                "error": "No questions generated — check scope/chapter_id mismatch",
            }

        if exam_id:
            exam_service = ExamService(db, redis_client)
            await exam_service.update_questions(
                exam_id=uuid.UUID(exam_id),
                questions=generated_questions,
                cost_report=result.get("cost_report"),
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
                    SSEvent.error(f"Exam generation failed: {status_val}", "orchestrator"),
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
    # and separate mcq_count/essay_count fields (from individual inputs)
    mcq_count = 0
    essay_count = 0
    qt = data.get("question_type", "")
    # Priority: use explicit mcq_count/essay_count from FE; fall back to total_questions
    explicit_mcq = data.get("mcq_count")
    explicit_essay = data.get("essay_count")
    total_q = data.get("total_questions", 10)

    if explicit_mcq is not None:
        mcq_count = int(explicit_mcq)
    if explicit_essay is not None:
        essay_count = int(explicit_essay)

    # If neither was provided, derive from question_type and total_questions
    if explicit_mcq is None and explicit_essay is None:
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
        user_prompt=data.get("user_prompt") or data.get("prompt") or None,
        extra_instructions=data.get("extra_instructions") or data.get("instructions") or None,
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
    await check_generate_rate_limit(redis, str(current_user.id))

    # Extract section titles from scope strings ("Chương > Phần" → "Phần")
    scope_sections: list[str] = []
    if config.scope and isinstance(config.scope, list):
        for s in config.scope:
            if isinstance(s, str) and " > " in s:
                section_part = s.split(" > ", 1)[1].strip()
                if section_part:
                    scope_sections.append(section_part)

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
                "scope_sections": scope_sections if scope_sections else None,
            },
        )
    except Exception as e:
        _log.exception("create_exam failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create exam: {e}")

    # NOTE: Scope size guard removed — with single namespace per document,
    # chunk count reflects the entire document. Retrieval handles scope
    # via metadata filter + per-chapter reranking + token budget cap.


    job_id = str(uuid.uuid4())
    exam_uuid = str(exam.id)
    _log.info("Starting generation: exam_id=%s, job_id=%s", exam.id, job_id)

    # Return response IMMEDIATELY with websocket_url, so frontend can connect
    # before generation events are emitted. Run generation as a background task.
    response = ExamGenerateResponse(
        exam_id=exam_uuid,
        job_id=job_id,
        message="Exam generation started.",
        websocket_url=f"{settings.ws_base_url}/ws/exam/{exam.id}",
        scope_warning=None,
    )

    async def _background_generation():
        """Run generation in background — emits events via WebSocket as it progresses."""
        import logging as _bg_log
        import sys as _sys
        from app.websocket.manager import get_connection_manager
        from langgraph.errors import GraphInterrupt
        _bg = _bg_log.getLogger("generate.background")
        _bg.setLevel(_bg_log.DEBUG)
        _bg.handlers.clear()
        _bg.addHandler(_bg_log.StreamHandler(_sys.stdout))
        _bg.propagate = False
        _bg.debug(">>> _background_generation STARTED for exam_id=%s", exam_uuid)
        _sys.stdout.flush()
        print(f"[DEBUG] _background_generation STARTED for exam_id={exam_uuid}", flush=True)
        try:
            result = await _run_generation_inline(
                exam_id=exam_uuid,
                user_id=str(current_user.id),
                document_id=str(config.document_id) if config.document_id else None,
                scope=config.scope,
                exam_config=exam.exam_config,
                user_prompt=config.user_prompt,
                extra_instructions=config.extra_instructions,
            )
            _bg.info("Generation completed (or paused) for exam_id=%s, status=%s",
                     exam_uuid, result.get("status"))
        except GraphInterrupt:
            _bg.info("Generation interrupted (HITL checkpoint) for exam_id=%s — waiting for frontend approval", exam_uuid)
        except TimeoutError:
            _bg.error("Generation timed out after 120s for exam_id=%s", exam_uuid)
            _mgr = get_connection_manager()
            await _mgr.emit(exam_uuid, {
                "type": "error",
                "message": "Generation timed out after 120 seconds.",
                "agent": "orchestrator",
            })
        except Exception as task_err:
            _bg.exception("Background generation failed for exam_id=%s: %s", exam_uuid, task_err)
            _mgr = get_connection_manager()
            await _mgr.emit(exam_uuid, {
                "type": "error",
                "message": str(task_err),
                "agent": "orchestrator",
            })

    # Start background task — shares the request's async event loop (no new loop needed)
    print(f"[DEBUG] About to create_task for exam_id={exam_uuid}", flush=True)
    asyncio.create_task(_background_generation())
    print(f"[DEBUG] create_task returned for exam_id={exam_uuid}", flush=True)

    _log.info("Response returned immediately for exam_id=%s, background task started", exam_uuid)
    return response


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
