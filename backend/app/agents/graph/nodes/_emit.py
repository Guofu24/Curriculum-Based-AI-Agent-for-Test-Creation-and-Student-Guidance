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

    This is a synchronous function — designed to be called from async nodes
    without awaiting, using asyncio.create_task so it never blocks the graph.
    All exceptions are swallowed to prevent _emit failures from crashing the
    graph pipeline.
    """
    try:
        from app.websocket.manager import get_connection_manager

        manager = get_connection_manager()
        exam_id = state.get("exam_id", "")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop (e.g. called from sync context) — skip
            return

        try:
            loop.create_task(manager.emit(exam_id, event))
        except Exception as e:
            # Swallow: WebSocket emit failures should not crash the graph
            logger.debug(f"_emit: create_task failed (non-critical): {e}")
    except Exception:
        # Swallow: WebSocket emit failures should not crash the graph
        pass
