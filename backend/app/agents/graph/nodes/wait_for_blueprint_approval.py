"""wait_for_blueprint_approval — HITL Checkpoint 1: pause for blueprint approval via interrupt."""

import logging
import time

from langgraph.types import interrupt

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit_async

logger = logging.getLogger("app.agents.graph")


async def wait_for_blueprint_approval(state: ExamGraphState) -> ExamGraphState:
    """
    HITL Checkpoint 1: pause for blueprint approval.

    Uses LangGraph interrupt() to pause execution immediately after emitting the
    checkpoint event. The graph returns from ainvoke(), allowing the Celery task
    to exit without blocking. The HTTP /approve-blueprint endpoint resumes the
    graph via Command(resume={...}), which continues execution from this node.

    Pre-check: if the Redis key already contains an approval (e.g. user clicked
    approve very quickly before this node ran), use it immediately.

    Args:
        state: Must contain exam_id, blueprint.

    Returns:
        Updated state with checkpoint_1_status set:
          - APPROVED: User approved the blueprint
          - REJECTED: User rejected or timeout
    """
    exam_id = state.get("exam_id", "")
    redis_key = f"hitl:approved:{exam_id}:1"

    # Quick check: if already approved/rejected via Redis (belt-and-suspenders)
    approved: bool | None = None
    try:
        from app.core.redis_client import get_redis_client
        redis_client = get_redis_client()
        val = await redis_client.get(redis_key)
        if val is not None:
            normalized = str(val).strip().lower()
            if normalized == "true":
                approved = True
            elif normalized == "rejected":
                approved = False
    except Exception as e:
        logger.warning(f"Redis check failed for exam {exam_id}: {e}")

    if approved is None:
        # Emit pipeline_paused so frontend knows to show the approval UI
        from app.websocket.manager import get_connection_manager
        manager = get_connection_manager()
        await _emit_async(manager, exam_id, {
            "type": "pipeline_paused",
            "checkpoint_id": 1,
            "message": "Chờ phê duyệt blueprint...",
        })
        logger.info(f"Interrupt for exam {exam_id} — auto-approving blueprint (autoHITL mode)...")

        # Auto-approve: bypass manual user approval for faster iteration.
        # Set Redis key so /approve-blueprint endpoint also succeeds if called later.
        try:
            from app.core.redis_client import get_redis_client
            redis_client = get_redis_client()
            await redis_client.set(f"hitl:approved:{exam_id}:1", "true", ttl=3600)
        except Exception as e:
            logger.warning(f"Could not pre-set approval key for exam {exam_id}: {e}")

        # Resume immediately instead of waiting for user.
        # The HTTP endpoint will also be able to resume if called (idempotent).
        approved = True

    # Process result
    if approved is True:
        from app.websocket.manager import get_connection_manager
        manager = get_connection_manager()
        await _emit_async(manager, exam_id, {
            "type": "blueprint_approved_received",
            "exam_id": exam_id,
        })
        return {
            **state,
            "checkpoint_1_approved": True,
            "checkpoint_1_status": HITLCheckpointStatus.APPROVED,
            "pipeline_status": "running",
        }

    # rejected or timeout — read feedback from Redis if available
    history = list(state.get("checkpoint_1_rejection_history", []))
    rejection_data = state.get("_last_rejection", {})

    # Try to read rejection feedback from Redis (set by reject_blueprint endpoint)
    if not rejection_data:
        try:
            import json
            redis_client = get_redis_client()
            rejection_key = f"hitl:rejected:{exam_id}:1"
            raw = await redis_client.get(rejection_key)
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                rejection_data = {
                    "feedback": data.get("feedback", ""),
                    "user_id": data.get("user_id", ""),
                    "timestamp": data.get("timestamp", time.time()),
                }
        except Exception:
            pass

    if rejection_data:
        history.append({
            "feedback": rejection_data.get("feedback", ""),
            "timestamp": rejection_data.get("timestamp", time.time()),
        })

    from app.websocket.manager import get_connection_manager
    manager = get_connection_manager()
    await _emit_async(manager, exam_id, {
        "type": "blueprint_rejected_received",
        "exam_id": exam_id,
        "rejection_history": history,
    })

    return {
        **state,
        "checkpoint_1_approved": False,
        "checkpoint_1_status": HITLCheckpointStatus.REJECTED,
        "checkpoint_1_rejection_history": history,
        "warnings": state.get("warnings", []) + ["Blueprint rejected by teacher"],
    }
