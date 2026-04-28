"""Exam generation Celery task."""

import asyncio
import uuid
import logging
from typing import Any

from celery import Task

from app.core.config import get_settings
from app.core.database import async_session_maker
from app.core.redis_client import get_redis_client
from app.services.exam_service import ExamService
from app.tasks.celery_app import celery_app
from app.websocket.manager import get_connection_manager, SSEvent

logger = logging.getLogger(__name__)
settings = get_settings()

# In-memory fallback for HITL approvals and graph state when Redis is unavailable.
# Key: exam_id, Value: {"approval": "approved"|"rejected"|None, "state": {...}}
_hitl_fallback_approvals: dict[str, dict] = {}


def set_fallback_approval(exam_id: str, value: str) -> None:
    """Set fallback approval in memory (used when Redis is unavailable)."""
    if exam_id not in _hitl_fallback_approvals:
        _hitl_fallback_approvals[exam_id] = {}
    _hitl_fallback_approvals[exam_id]["approval"] = value


def get_fallback_approval(exam_id: str) -> str | None:
    """Get fallback approval from memory."""
    return _hitl_fallback_approvals.get(exam_id, {}).get("approval")


def set_fallback_graph_state(exam_id: str, state: dict) -> None:
    """Save graph state when pausing at HITL checkpoint (used when Redis is unavailable)."""
    _hitl_fallback_approvals[exam_id] = {
        "approval": None,
        "state": state,
    }


def get_fallback_graph_state(exam_id: str) -> dict | None:
    """Get saved graph state after approval."""
    entry = _hitl_fallback_approvals.get(exam_id)
    return entry.get("state") if entry else None


def _build_demo_payload(
    exam_id: str | None,
    scope: list | None,
    exam_config: dict | None,
    user_prompt: str | None,
) -> dict[str, Any]:
    """Build deterministic demo questions so the UI can be shown without full AI deps."""
    exam_config = exam_config or {}
    scope = list(scope or exam_config.get("scope") or ["Chuong 1"])
    prompt = user_prompt or exam_config.get("user_prompt") or "De kiem tra demo"
    mcq_count = min(int(exam_config.get("mcq_count", 6) or 6), 12)
    essay_count = min(int(exam_config.get("essay_count", 1) or 1), 3)
    bloom_distribution = exam_config.get("bloom_distribution") or {
        "nhan_biet": 20,
        "thong_hieu": 30,
        "van_dung": 30,
        "van_dung_cao": 20,
    }
    bloom_levels = [k for k, v in bloom_distribution.items() if v > 0] or ["nhan_biet"]
    stem_seed = prompt[:80]

    questions: list[dict[str, Any]] = []
    for index in range(mcq_count):
        bloom = bloom_levels[index % len(bloom_levels)]
        chapter = scope[index % len(scope)]
        qid = f"MCQ_{index + 1:03d}"
        questions.append(
            {
                "id": qid,
                "question_id": qid,
                "type": "mcq",
                "question_type": "mcq",
                "stem": f"[DEMO] {chapter}: Cau hoi {index + 1} cho yeu cau '{stem_seed}'",
                "content": f"[DEMO] {chapter}: Cau hoi {index + 1} cho yeu cau '{stem_seed}'",
                "options": {
                    "A": "Lua chon A",
                    "B": "Lua chon B",
                    "C": "Lua chon C",
                    "D": "Lua chon D",
                },
                "correct_answer": ["A", "B", "C", "D"][index % 4],
                "bloom_level": bloom,
                "difficulty_level": "medium",
                "quality_score": 0.92,
                "warnings": [],
                "source_evidence": [],
                "source_citations": [f"Demo source: {chapter}"],
                "verification_status": "passed",
                "is_validated": True,
            }
        )

    for index in range(essay_count):
        bloom = bloom_levels[(mcq_count + index) % len(bloom_levels)]
        chapter = scope[index % len(scope)]
        qid = f"ESSAY_{index + 1:03d}"
        questions.append(
            {
                "id": qid,
                "question_id": qid,
                "type": "essay",
                "question_type": "essay",
                "stem": f"[DEMO] {chapter}: Tu luan {index + 1} cho yeu cau '{stem_seed}'",
                "content": f"[DEMO] {chapter}: Tu luan {index + 1} cho yeu cau '{stem_seed}'",
                "rubric": [
                    {"score": 0.5, "description": "Neu dung y chinh"},
                    {"score": 0.5, "description": "Lap luan ro rang"},
                ],
                "correct_answer": "Tra loi theo dap an mau",
                "bloom_level": bloom,
                "difficulty_level": "medium",
                "quality_score": 0.9,
                "warnings": [],
                "source_evidence": [],
                "source_citations": [f"Demo source: {chapter}"],
                "verification_status": "passed",
                "is_validated": True,
            }
        )

    by_chapter = {
        chapter: sum(1 for q in questions if chapter in (q.get("source_citations") or [""])[0])
        for chapter in scope
    }
    blueprint = {
        "distribution": bloom_distribution,
        "chapters": [
            {
                "name": chapter,
                "nhan_biet": sum(1 for q in questions if q.get("bloom_level") == "nhan_biet" and chapter in (q.get("source_citations") or [""])[0]),
                "thong_hieu": sum(1 for q in questions if q.get("bloom_level") == "thong_hieu" and chapter in (q.get("source_citations") or [""])[0]),
                "van_dung": sum(1 for q in questions if q.get("bloom_level") == "van_dung" and chapter in (q.get("source_citations") or [""])[0]),
                "van_dung_cao": sum(1 for q in questions if q.get("bloom_level") == "van_dung_cao" and chapter in (q.get("source_citations") or [""])[0]),
            }
            for chapter in scope
        ],
        "summary": {"by_chapter": by_chapter},
    }

    # Build blueprint as a list-of-slots (one per question) so update_questions() can
    # persist it to the dedicated `blueprint` DB column and the frontend can display it.
    blueprint_slots: list[dict] = [
        {
            "question_id": q.get("id") or q.get("question_id", f"Q_{i + 1}"),
            "type": q.get("type") or q.get("question_type", "mcq"),
            "bloom_level": q.get("bloom_level", "thong_hieu"),
            "chapter": (q.get("source_citations") or [scope[i % len(scope)]])[0] if scope else "",
            "topic_hint": q.get("topic_hint", ""),
            "estimated_difficulty": float(q.get("estimated_difficulty", 0.5)),
        }
        for i, q in enumerate(questions)
        if isinstance(q, dict)
    ]

    return {
        "exam_id": exam_id,
        "questions": questions,
        "blueprint": blueprint_slots,  # list-of-slots so isinstance(result["blueprint"], list) is True
        "blueprint_summary": blueprint,  # dict format kept for distribution table
        "distribution_summary": {
            "by_bloom": {
                level: sum(1 for q in questions if q.get("bloom_level") == level)
                for level in bloom_levels
            },
            "by_chapter": by_chapter,
        },
        "cost_report": {
            "mode": "demo",
            "breakdown": {"demo_generator": {"total_tokens": 0, "estimated_cost_usd": 0.0}},
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "blueprint": blueprint,
        },
        "status": "success",
        "warnings": ["Demo mode: generated local sample questions."],
    }


def _run_async_task(
    exam_id: str | None,
    user_id: str | None,
    document_id: str | None,
    scope: list | None,
    exam_config: dict | None,
    user_prompt: str | None,
    extra_instructions: str | None,
) -> dict:
    """
    Synchronous wrapper that runs the async generation pipeline.
    Executed via ThreadPoolExecutor to avoid asyncio conflicts in Celery.
    Uses loop.run_until_complete() instead of asyncio.run() to avoid
    creating a nested event loop inside the already-running executor thread.
    """
    trace_id = str(uuid.uuid4())

    async def _run():
        async with async_session_maker() as db:
            redis_client = get_redis_client()
            manager = get_connection_manager()

            from app.observability.tracer import get_tracer
            tracer = get_tracer()

            trace_meta = {
                "user_id": user_id,
                "document_id": document_id,
                "scope": scope,
                "bloom_distribution": (exam_config or {}).get("bloom_distribution"),
                "demo_mode": settings.DEMO_MODE or not document_id,
            }

            # Setup stream callback for WebSocket + Redis pub/sub
            async def stream_callback(event: dict):
                channel = exam_id if exam_id else f"trace:{trace_id}"
                await manager.emit(channel, event)

            with tracer.trace(exam_id=exam_id or trace_id, metadata=trace_meta):
                await manager.emit(
                    exam_id or trace_id,
                    SSEvent.plan_step("Bat dau sinh de...", 0, 5),
                )

                use_demo_mode = settings.DEMO_MODE or not document_id
                if use_demo_mode:
                    await manager.emit(
                        exam_id or trace_id,
                        SSEvent.plan_step("Dang tao de demo local...", 1, 5),
                    )
                    result = _build_demo_payload(exam_id, scope, exam_config, user_prompt)
                    for question in result["questions"]:
                        await manager.emit(
                            exam_id or trace_id,
                            SSEvent.question_generated(
                                question_id=question.get("question_id", ""),
                                question=question,
                            ),
                        )
                    await manager.emit(
                        exam_id or trace_id,
                        SSEvent.validation_result(
                            passed=True,
                            issues_count=0,
                            issues=[],
                        ),
                    )
                    await manager.emit(
                        exam_id or trace_id,
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
                        exam_id or trace_id,
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
                    # Import here to avoid circular imports and to skip heavy stack in demo mode
                    from app.agents.orchestrator import OrchestratorAgent

                    orchestrator = OrchestratorAgent(redis=redis_client, db_session=db)
                    orchestrator.set_stream_callback(stream_callback)
                    result = await orchestrator.generate_exam(
                        exam_id=exam_id,
                        user_id=user_id,
                        exam_config=exam_config or {},
                        user_prompt=user_prompt,
                        extra_instructions=extra_instructions,
                        document_id=document_id,
                    )

                # Emit blueprint if pipeline is paused (before waiting for approval)
                # This happens when wait_for_blueprint_approval returned PENDING
                if result.get("pipeline_paused") and result.get("blueprint"):
                    blueprint_slots = result.get("blueprint", [])
                    await manager.emit(
                        exam_id,
                        {
                            "type": "hitl_checkpoint",
                            "checkpoint_id": 1,
                            "data": {
                                "blueprint": blueprint_slots,
                                "distribution_summary": result.get("distribution_summary", {}),
                            },
                        },
                    )
                    # ── Persist blueprint to DB so page refresh shows it ──
                    if exam_id and isinstance(blueprint_slots, list) and blueprint_slots:
                        try:
                            exam_service = ExamService(db, redis_client)
                            await exam_service.update_blueprint(
                                exam_id=uuid.UUID(exam_id),
                                blueprint=blueprint_slots,
                            )
                        except Exception as _bp_err:
                            logger.warning("Failed to persist blueprint to DB: %s", _bp_err)

                if exam_id:
                    # Only update DB and emit completion if NOT paused at a checkpoint.
                    # If paused, the background polling task will resume the graph
                    # and emit the final events when approval arrives.
                    if not result.get("pipeline_paused"):
                        if result.get("questions"):
                            exam_service = ExamService(db, redis_client)
                            await exam_service.update_questions(
                                exam_id=uuid.UUID(exam_id),
                                questions=result.get("questions", []),
                                cost_report=result.get("cost_report"),
                                blueprint=result.get("blueprint") if isinstance(result.get("blueprint"), list) else None,
                            )

                        status_val = result.get("status")
                        is_success = (
                            status_val == "success"
                            or (hasattr(status_val, "value") and status_val.value == "success")
                            or status_val == "partial"
                        )

                        if is_success:
                            await manager.emit(
                                exam_id,
                                SSEvent.completed(
                                    exam_id,
                                    total_cost_usd=result.get("cost_report", {}).get("total_cost_usd"),
                                )
                            )
                        else:
                            await manager.emit(
                                exam_id,
                                SSEvent.error(
                                    f"Exam generation failed: {status_val}",
                                    "orchestrator",
                                ),
                            )

                return {
                    "exam_id": exam_id,
                    "status": str(result.get("status", "unknown")),
                    "trace_id": trace_id,
                }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()
            asyncio.set_event_loop(None)
    except BaseException as e:
        # Handle GraphInterrupt — expected when HITL checkpoint pauses the graph.
        # The graph state is saved in the checkpointer; HTTP endpoint resumes it.
        try:
            from langgraph.types import GraphInterrupt as _GI
            is_interrupt = isinstance(e, _GI)
        except ImportError:
            is_interrupt = False

        if is_interrupt:
            if exam_id:
                try:
                    err_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(err_loop)
                    try:
                        manager = get_connection_manager()
                        err_loop.run_until_complete(
                            manager.emit(exam_id, {
                                "type": "pipeline_paused",
                                "checkpoint_id": 1,
                                "message": "Đang chờ phê duyệt blueprint...",
                            }),
                        )
                    finally:
                        err_loop.close()
                        asyncio.set_event_loop(None)
                except Exception:
                    pass
            return {
                "exam_id": exam_id,
                "status": "paused_at_checkpoint",
                "message": "Pipeline paused at HITL checkpoint, waiting for approval.",
                "trace_id": trace_id,
            }

        if exam_id:
            try:
                err_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(err_loop)
                try:
                    manager = get_connection_manager()
                    err_loop.run_until_complete(
                        manager.emit(exam_id, SSEvent.error(str(e), "orchestrator")),
                    )
                finally:
                    err_loop.close()
                    asyncio.set_event_loop(None)
            except Exception:
                logger.error("Failed to emit error event for exam %s: %s", exam_id, e)
        raise


@celery_app.task(
    bind=True,
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    ignore_result=False,
)
def generate_exam_task(
    self: Task,
    exam_id: str | None = None,
    user_id: str | None = None,
    document_id: str | None = None,
    scope: list | None = None,
    exam_config: dict | None = None,
    user_prompt: str | None = None,
    extra_instructions: str | None = None,
) -> dict:
    """
    Run the full multi-agent exam generation pipeline.

    Idempotency: checks Redis key task:started:{exam_id} to prevent
    duplicate execution when Celery retries the same task.
    """
    # Idempotency guard: prevent duplicate execution on Celery retry
    if exam_id:
        try:
            redis_client = get_redis_client()
            task_key = f"task:started:{exam_id}"
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                already_running = loop.run_until_complete(redis_client.get(task_key))
                if already_running:
                    logger.info("Task already running for exam %s, skipping duplicate execution", exam_id)
                    return {"status": "already_running", "exam_id": exam_id}
                loop.run_until_complete(redis_client.set(task_key, "1", ttl=7200))
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        except Exception as e:
            logger.warning("Idempotency check failed for exam %s: %s", exam_id, e)
    # Use _run_async_task directly - it handles event loop internally
    return _run_async_task(
        exam_id=exam_id,
        user_id=user_id,
        document_id=document_id,
        scope=scope,
        exam_config=exam_config,
        user_prompt=user_prompt,
        extra_instructions=extra_instructions,
    )


