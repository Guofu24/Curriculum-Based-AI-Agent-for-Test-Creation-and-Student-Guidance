"""wait_for_review — HITL Checkpoint 2: pause for exam review via interrupt."""

import logging
import time

from langgraph.types import interrupt

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit_async

logger = logging.getLogger("app.agents.graph")

# Timeout for HITL Checkpoint 2: 60 minutes
HITL_CHECKPOINT_2_TIMEOUT = 3600.0


def _normalize(val) -> str:
    """Normalize Redis value to lowercase string for comparison."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode().strip().lower()
    return str(val).strip().lower()


def _process_review_result(
    state: ExamGraphState,
    approved: bool,
) -> ExamGraphState:
    """Process the review approval/rejection result and return state update."""
    exam_id = state.get("exam_id", "")

    import asyncio
    try:
        from app.websocket.manager import get_connection_manager
        loop = asyncio.get_running_loop()
        event_type = "exam_review_approved_received" if approved else "exam_review_rejected_received"
        loop.create_task(_emit_async(get_connection_manager(), exam_id, {
            "type": event_type,
            "exam_id": exam_id,
        }))
    except Exception:
        pass

    if approved:
        return {
            **state,
            "checkpoint_2_approved": True,
            "checkpoint_2_status": HITLCheckpointStatus.APPROVED,
            "review_approved": True,
        }

    return {
        **state,
        "checkpoint_2_approved": False,
        "checkpoint_2_status": HITLCheckpointStatus.REJECTED,
    }


async def wait_for_review(state: ExamGraphState) -> ExamGraphState:
    """
    HITL Checkpoint 2: pause for exam review using LangGraph interrupt().

    Uses langgraph.types.interrupt() to pause execution. The graph returns
    from ainvoke() with __interrupt__ in the result. The Celery task exits
    cleanly. The HTTP /approve-review endpoint resumes the graph via
    Command(resume={...}).

    Pre-check: if Redis key already contains approval, skip interrupt and
    proceed immediately.

    Args:
        state: Must contain exam_id, checkpoint_2_timeout_at, questions.

    Returns:
        Updated state with checkpoint_2_approved and checkpoint_2_status set.
    """
    exam_id = state.get("exam_id", "")
    current_time = time.time()
    timeout_at = state.get("checkpoint_2_timeout_at") or (current_time + HITL_CHECKPOINT_2_TIMEOUT)
    questions = state.get("questions", [])

    # Check timeout first
    if current_time >= timeout_at:
        logger.warning(f"Checkpoint 2 timeout for exam {exam_id}")
        return {
            **state,
            "checkpoint_2_approved": False,
            "checkpoint_2_status": HITLCheckpointStatus.REJECTED,
            "error": "Review timeout",
            "warnings": state.get("warnings", []) + ["HITL Checkpoint 2 timeout"],
        }

    redis_key = f"hitl:approved:{exam_id}:2"

    # Quick check: if already approved/rejected via Redis
    approved: bool | None = None
    try:
        from app.core.redis_client import get_redis_client
        redis_client = get_redis_client()
        val = await redis_client.get(redis_key)
        if val is not None:
            normalized = _normalize(val)
            if normalized == "true":
                approved = True
            elif normalized == "rejected":
                approved = False
    except Exception as e:
        logger.warning(f"Redis check failed for exam {exam_id}: {e}")

    if approved is not None:
        # Already resolved — proceed without interrupt
        return _process_review_result(state, approved)

    # Emit pipeline_paused so frontend knows to show the review UI
    from app.websocket.manager import get_connection_manager
    try:
        manager = get_connection_manager()
        await _emit_async(manager, exam_id, {
            "type": "pipeline_paused",
            "checkpoint_id": 2,
            "message": "Chờ giảng viên duyệt đề...",
            "questions_count": len(questions),
        })
    except Exception as e:
        logger.warning(f"Failed to emit pipeline_paused for exam {exam_id}: {e}")

    logger.info(f"Interrupting graph for exam {exam_id} — waiting for exam review")

    # Domain 8: Use LangGraph interrupt to pause the graph.
    # This causes ainvoke() to return {"__interrupt__": [...]} instead of continuing.
    # The Celery task exits cleanly. HTTP endpoint resumes via Command(resume={...}).
    raise interrupt({
        "type": "exam_review",
        "exam_id": exam_id,
        "redis_key": redis_key,
        "message": "Waiting for teacher to review the exam",
        "timeout_at": timeout_at,
    })


async def _poll_for_review(
    redis_client,
    redis_key: str,
    timeout_at: float,
) -> bool | None:
    """Fallback polling when pub/sub fails."""
    import asyncio
    interval = 2.0
    while time.time() < timeout_at:
        val = await redis_client.get(redis_key)
        if val is not None:
            normalized = _normalize(val)
            if normalized == "true":
                return True
            if normalized == "rejected":
                return False
        await asyncio.sleep(interval)
    return None
