"""Exam generation Celery task."""

import asyncio
import uuid

from celery import Task

from app.tasks.celery_app import celery_app
from app.core.database import async_session_maker
from app.core.redis_client import get_redis_client, RedisClient
from app.services.exam_service import ExamService
from app.websocket.manager import get_connection_manager, SSEvent


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

            async def stream_callback(event: dict):
                channel = f"exam:{exam_id}" if exam_id else f"trace:{trace_id}"
                await manager.emit(channel, event)

            # Import here to avoid circular imports
            from app.agents.orchestrator import OrchestratorAgent

            orchestrator = OrchestratorAgent(redis=redis_client, db_session=db)
            orchestrator.set_stream_callback(stream_callback)

            try:
                await manager.emit(
                    f"exam:{exam_id}",
                    SSEvent.plan_step("Bat dau sinh de...", 0, 5)
                )

                result = await orchestrator.generate_exam(
                    user_id=user_id,
                    document_id=document_id,
                    scope=scope or [],
                    exam_config=exam_config or {},
                    user_prompt=user_prompt,
                    extra_instructions=extra_instructions,
                    trace_id=trace_id,
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
                            f"exam:{exam_id}",
                            SSEvent.completed(exam_id)
                        )
                    else:
                        await manager.emit(
                            f"exam:{exam_id}",
                            SSEvent.error(
                                "Exam generation completed with warnings",
                                "orchestrator"
                            )
                        )

                return {
                    "exam_id": exam_id,
                    "status": str(result.get("status", "unknown")),
                    "trace_id": trace_id,
                }

            except Exception as e:
                if exam_id:
                    await manager.emit(
                        f"exam:{exam_id}",
                        SSEvent.error(str(e), "orchestrator")
                    )
                raise

    # Use run_until_complete to avoid nested event loop in ThreadPoolExecutor
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - create one (standard Celery worker case)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()
    else:
        # Already in an event loop - create a new task and run it
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(loop.run_until_complete, _run())
            return future.result()


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

    Steps:
    1. Load exam record from DB
    2. Orchestrator: execute full pipeline
    3. Emit WebSocket events via Redis pub/sub
    4. Save result + cost_report to DB
    5. Update exam status
    """
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


@celery_app.task(bind=True, max_retries=2, ignore_result=True)
def regenerate_questions_task(
    self: Task,
    exam_id: str,
    user_id: str,
    question_ids: list[str] | None = None,
) -> dict:
    """Regenerate specific questions or all questions."""
    trace_id = str(uuid.uuid4())

    async def _run():
        async with async_session_maker() as db:
            return {"exam_id": exam_id, "status": "pending", "trace_id": trace_id}

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()
    else:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(loop.run_until_complete, _run())
            return future.result()
