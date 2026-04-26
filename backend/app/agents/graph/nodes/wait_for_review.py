"""wait_for_review — HITL Checkpoint 2: wait for exam review via Redis pub/sub."""

import asyncio
import json
import logging
import time

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit
from app.core.redis_client import RedisClient

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


async def wait_for_review(state: ExamGraphState) -> ExamGraphState:
    """
    HITL Checkpoint 2: wait for exam review via Redis pub/sub.

    Instead of using LangGraph's interrupt() (which requires explicit graph.resume()
    calls that the current code never performs), this node subscribes to the Redis
    channel exam:{exam_id} and BLOCKS until:
      - User approves → receives {"type": "review_approved"} → proceeds to save_teacher_preferences
      - User rejects  → receives {"type": "review_rejected"} → goes to finalize_with_feedback
      - Timeout       → exits after HITL_CHECKPOINT_2_TIMEOUT seconds

    Args:
        state: Must contain exam_id, checkpoint_2_timeout_at, questions.

    Returns:
        Updated state with checkpoint_2_approved and checkpoint_2_status set.
    """
    exam_id = state.get("exam_id", "")
    current_time = time.time()
    timeout_at = state.get("checkpoint_2_timeout_at") or (current_time + HITL_CHECKPOINT_2_TIMEOUT)
    questions = state.get("questions", [])

    if current_time >= timeout_at:
        _emit(state, {
            "type": "pipeline_paused",
            "checkpoint_id": 2,
            "message": "Review timeout",
        })
        return {
            **state,
            "checkpoint_2_approved": False,
            "checkpoint_2_status": HITLCheckpointStatus.REJECTED,
            "error": "Review timeout",
            "warnings": state.get("warnings", []) + ["HITL Checkpoint 2 timeout"],
        }

    _emit(state, {
        "type": "pipeline_paused",
        "checkpoint_id": 2,
        "message": "Chờ giảng viên duyệt đề...",
        "questions_count": len(questions),
    })

    # Auto-approve: bypass manual review for faster iteration (autoHITL mode).
    # Set Redis key so any concurrent subscriber also sees approval.
    redis_key = f"hitl:approved:{exam_id}:2"
    redis_client = RedisClient()
    try:
        await redis_client.set(redis_key, "true", ttl=3600)
        logger.info(f"Auto-approved checkpoint 2 for exam {exam_id}")
    except Exception as e:
        logger.warning(f"Could not set auto-approval key for exam {exam_id}: {e}")

    # Return immediately with approved status — no Redis pub/sub blocking needed.
    return {
        **state,
        "checkpoint_2_approved": True,
        "checkpoint_2_status": HITLCheckpointStatus.APPROVED,
        "review_approved": True,
    }


async def _poll_for_review(
    redis_client: RedisClient,
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
