"""Document processing Celery task."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from celery import Task

from app.tasks.celery_app import celery_app
from app.core.database import async_session_maker
from app.services.document_service import DocumentService
from app.websocket.manager import get_connection_manager, SSEvent


def _run_document_task(document_id: str) -> dict:
    """Synchronous wrapper for document processing."""

    async def _run():
        async with async_session_maker() as db:
            from app.core.redis_client import get_redis_client
            redis = get_redis_client()
            service = DocumentService(db, redis)
            manager = get_connection_manager()

            try:
                await manager.emit(
                    f"doc:{document_id}",
                    SSEvent.progress(10, "Đang tải tài liệu...")
                )

                result = await service.process_document(uuid.UUID(document_id))

                # Handle both "processed" and "completed" status values
                if result.get("status") in ("completed", "processed"):
                    await manager.emit(
                        f"doc:{document_id}",
                        SSEvent.progress(100, "Hoàn thành xử lý!")
                    )
                else:
                    await manager.emit(
                        f"doc:{document_id}",
                        SSEvent.error(result.get("error", "Processing failed"), "document")
                    )

                return result

            except Exception as e:
                await manager.emit(
                    f"doc:{document_id}",
                    SSEvent.error(str(e), "document")
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
    else:
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
