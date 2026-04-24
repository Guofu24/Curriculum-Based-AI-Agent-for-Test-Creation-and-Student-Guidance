"""Document processing Celery task."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from celery import Task

from app.tasks.celery_app import celery_app
from app.core.database import async_session_maker
from app.services.document_service import DocumentService
from app.websocket.manager import get_document_upload_manager, SSEvent


def _run_document_task(document_id: str) -> dict:
    """Synchronous wrapper for document processing."""

    async def _run():
        async with async_session_maker() as db:
            from app.core.redis_client import get_redis_client
            redis = get_redis_client()
            service = DocumentService(db, redis)
            manager = get_document_upload_manager()

            try:
                # Emit: queued (before service.process_document takes over)
                await manager.broadcast(
                    document_id,
                    SSEvent.processing_step(
                        document_id, "queued",
                        "Đang chờ xử lý...", 5
                    ),
                )

                result = await service.process_document(uuid.UUID(document_id))

                if result.get("processing_status") == "completed":
                    await manager.broadcast(
                        document_id,
                        SSEvent.processing_step(
                            document_id, "done",
                            "Hoàn thành xử lý!", 100
                        ),
                    )
                else:
                    await manager.broadcast(
                        document_id,
                        SSEvent.processing_failed(
                            document_id, result.get("error", "Processing failed")
                        ),
                    )

                return result

            except Exception as e:
                await manager.broadcast(
                    document_id,
                    SSEvent.processing_failed(document_id, str(e)),
                )
                raise

    # Use the same safe pattern as exam_task.py
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_run())
        finally:
            loop.close()
    # Safe async-in-thread pattern: when a running loop exists, delegate to a
    # thread pool so we don't nest event loops.  Using 8 workers lets this Celery
    # process handle multiple documents concurrently while Celery itself manages the
    # multi-process parallelism (start Celery with --concurrency=N for true scale-out).
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
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
def process_document_task(
    self: Task,
    document_id: str,
) -> dict:
    """
    Run the full RAG pipeline for a document.

    Steps:
    1. Download from S3
    2. Parse + structure detection
    3. Formula + image extraction
    4. Chunking
    5. Embed + upsert Pinecone
    6. Update DB status
    7. Emit WebSocket status event
    """
    return _run_document_task(document_id)
