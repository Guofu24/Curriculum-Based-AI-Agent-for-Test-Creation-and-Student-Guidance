"""Shared WebSocket emit helper for all graph nodes.

All graph nodes call _emit(state, event) to push events to the frontend
via the WebSocket connection for the current exam.
"""

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


def _emit(state: "ExamGraphState", event: dict) -> None:
    """
    Emit a WebSocket event for the exam in `state`.

    This is a synchronous wrapper around _emit_async — designed to be called
    from sync contexts without awaiting, using asyncio.create_task so it never
    blocks the caller. All exceptions are swallowed to prevent _emit failures
    from crashing the graph pipeline.
    """
    try:
        from app.websocket.manager import get_connection_manager

        manager = get_connection_manager()
        exam_id = state.get("exam_id", "")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        try:
            loop.create_task(_emit_async(manager, exam_id, event))
        except Exception as e:
            logger.debug("_emit: create_task failed (non-critical): %s", e)
    except Exception as e:
        logger.debug("_emit: setup failed (non-critical): %s", e)


async def _emit_async(manager, exam_id: str, event: dict) -> None:
    """
    Async version of _emit. Properly awaits the WebSocket send so events are
    confirmed before the caller continues. Use this when you need to ensure
    events reach the frontend before proceeding (e.g. before interrupt()).
    """
    try:
        event_type = event.get("type", "unknown")
        print(f"[DEBUG _emit_async] exam_id={exam_id}, type={event_type}, has_manager={manager is not None}", flush=True)
        await manager.emit(exam_id, event)
        print(f"[DEBUG _emit_async] SUCCESS: exam_id={exam_id}, type={event_type}", flush=True)
    except Exception as e:
        print(f"[DEBUG _emit_async] FAILED: exam_id={exam_id}, type={event.get('type','?')}, error={e}", flush=True)
        logger.debug(f"_emit_async: emit failed (non-critical): {e}")
