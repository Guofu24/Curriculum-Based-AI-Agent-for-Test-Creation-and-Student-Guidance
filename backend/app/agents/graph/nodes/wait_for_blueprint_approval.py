"""wait_for_blueprint_approval — HITL Checkpoint 1: pause for blueprint approval via interrupt."""

import logging
import time

from langgraph.types import interrupt

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit_async

logger = logging.getLogger("app.agents.graph")

# Timeout for HITL Checkpoint 1: 30 minutes
HITL_CHECKPOINT_1_TIMEOUT = 1800.0


def _normalize(val) -> str:
    """Normalize Redis value to lowercase string for comparison."""
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode().strip().lower()
    return str(val).strip().lower()


def _process_approval_result(
    state: ExamGraphState,
    approved: bool,
    rejection_data: dict | None = None,
) -> ExamGraphState:
    """Process the approval/rejection result and return state update."""
    exam_id = state.get("exam_id", "")

    if approved:
        # Emit blueprint_approved_received event
        import asyncio
        try:
            from app.websocket.manager import get_connection_manager
            loop = asyncio.get_running_loop()
            loop.create_task(_emit_async(get_connection_manager(), exam_id, {
                "type": "blueprint_approved_received",
                "exam_id": exam_id,
            }))
        except Exception as exc:
            logger.debug("Failed to emit blueprint_approved_received: %s", exc)

        return {
            **state,
            "checkpoint_1_approved": True,
            "checkpoint_1_status": HITLCheckpointStatus.APPROVED,
            "pipeline_status": "running",
        }

    # Rejected or timeout
    history = list(state.get("checkpoint_1_rejection_history", []))
    if rejection_data:
        history.append({
            "feedback": rejection_data.get("feedback", ""),
            "timestamp": rejection_data.get("timestamp", time.time()),
        })
    elif not history:
        history.append({
            "feedback": "Timeout",
            "timestamp": time.time(),
        })

    import asyncio
    try:
        from app.websocket.manager import get_connection_manager
        loop = asyncio.get_running_loop()
        loop.create_task(_emit_async(get_connection_manager(), exam_id, {
            "type": "blueprint_rejected_received",
            "exam_id": exam_id,
            "rejection_history": history,
        }))
    except Exception as exc:
        logger.debug("Failed to emit blueprint_rejected_received: %s", exc)

    return {
        **state,
        "checkpoint_1_approved": False,
        "checkpoint_1_status": HITLCheckpointStatus.REJECTED,
        "checkpoint_1_rejection_history": history,
        "warnings": state.get("warnings", []) + ["Blueprint rejected or timed out"],
    }


async def wait_for_blueprint_approval(state: ExamGraphState) -> ExamGraphState:
    """
    HITL Checkpoint 1: pause for blueprint approval using LangGraph interrupt().

    Uses langgraph.types.interrupt() to pause execution. The graph returns
    from ainvoke() raising GraphInterrupt. The HTTP /approve-blueprint endpoint
    resumes the graph via Command(resume={...}).

    Pre-check: if Redis key already contains approval, skip interrupt and
    proceed immediately (supports resume after approval was already given).

    Args:
        state: Must contain exam_id, blueprint.

    Returns:
        Updated state with checkpoint_1_status set:
          - APPROVED: User approved the blueprint
          - REJECTED: User rejected
    """
    exam_id = state.get("exam_id", "")
    redis_key = f"hitl:approved:{exam_id}:1"

    # Quick check: if already approved/rejected via Redis (belt-and-suspenders)
    approved: bool | None = None
    rejection_data: dict | None = None
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
        # Also check for rejection data
        if approved is False:
            rejection_key = f"hitl:rejected:{exam_id}:1"
            raw = await redis_client.get(rejection_key)
            if raw:
                import json
                data = json.loads(raw) if isinstance(raw, str) else raw
                rejection_data = {
                    "feedback": data.get("feedback", ""),
                    "timestamp": data.get("timestamp", time.time()),
                }
    except Exception as e:
        logger.warning(f"Redis check failed for exam {exam_id}: {e}")

    if approved is not None:
        # Already resolved — proceed without interrupt
        logger.info(
            "[wait_for_blueprint_approval] Redis has decision for exam %s: approved=%s",
            exam_id, approved,
        )
        return _process_approval_result(state, approved, rejection_data)

    # Emit pipeline_paused so frontend knows to show the approval UI
    from app.websocket.manager import get_connection_manager
    try:
        manager = get_connection_manager()
        await _emit_async(manager, exam_id, {
            "type": "pipeline_paused",
            "checkpoint_id": 1,
            "message": "Chờ phê duyệt blueprint...",
        })
    except Exception as e:
        logger.warning(f"Failed to emit pipeline_paused for exam {exam_id}: {e}")

    logger.info(f"Interrupting graph for exam {exam_id} — waiting for blueprint approval")

    # Use LangGraph interrupt() to pause the graph.
    # interrupt() raises GraphInterrupt internally — ainvoke() catches it
    # and saves graph state to the checkpointer for later resume.
    resume_value = interrupt({
        "type": "blueprint_approval",
        "exam_id": exam_id,
        "redis_key": redis_key,
        "message": "Waiting for teacher to approve or reject the blueprint",
    })

    # This code runs ONLY after graph is resumed via Command(resume=...)
    logger.info(
        "[wait_for_blueprint_approval] Resumed for exam %s with value: %s",
        exam_id, resume_value,
    )

    # Process the resume value
    if isinstance(resume_value, dict):
        is_approved = resume_value.get("approved", False)
        if not is_approved:
            rejection_data = {
                "feedback": resume_value.get("feedback", ""),
                "timestamp": resume_value.get("timestamp", time.time()),
            }
        return _process_approval_result(state, is_approved, rejection_data)

    # Simple boolean resume
    return _process_approval_result(state, bool(resume_value))

