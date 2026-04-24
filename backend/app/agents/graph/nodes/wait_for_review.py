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

    # Quick check Redis key (belt-and-suspenders)
    redis_key = f"hitl:approved:{exam_id}:2"
    redis_client = RedisClient()
    initial_val = await redis_client.get(redis_key)
    if initial_val is not None:
        normalized = _normalize(initial_val)
        if normalized == "true":
            return {
                **state,
                "checkpoint_2_approved": True,
                "checkpoint_2_status": HITLCheckpointStatus.APPROVED,
                "review_approved": True,
            }
        if normalized == "rejected":
            return {
                **state,
                "checkpoint_2_approved": False,
                "checkpoint_2_status": HITLCheckpointStatus.REJECTED,
                "checkpoint_2_feedback": None,
            }

    # Subscribe to Redis channel and wait
    channel = f"exam:{exam_id}"
    approval_received = None  # None = waiting, True = approved, False = rejected

    try:
        sub = redis_client.client.pubsub()
        await sub.subscribe(channel)
        logger.info(f"Subscribed to Redis channel '{channel}', waiting for exam review...")

        start_time = time.time()
        while approval_received is None:
            elapsed = time.time() - start_time
            remaining = timeout_at - time.time()
            if remaining <= 0:
                logger.warning(f"Exam review timeout for exam {exam_id}")
                break

            # Check Redis key periodically
            val = await redis_client.get(redis_key)
            if val is not None:
                normalized = _normalize(val)
                if normalized == "true":
                    approval_received = True
                    break
                if normalized == "rejected":
                    approval_received = False
                    break

            # Wait for message on channel
            msg = await sub.get_message(ignore_subscribe_messages=True, timeout=2.0)
            if msg and msg.get("type") == "message":
                data = msg.get("data", "")
                try:
                    event = json.loads(data) if isinstance(data, str) else data
                    event_type = event.get("type", "") if isinstance(event, dict) else ""
                    if event_type in ("review_approved", "hitl_approved"):
                        approval_received = True
                        break
                    if event_type in ("review_rejected", "hitl_rejected"):
                        approval_received = False
                        break
                except Exception:
                    pass

        await sub.unsubscribe(channel)
        await sub.aclose()
    except asyncio.CancelledError:
        try:
            await sub.unsubscribe(channel)
            await sub.aclose()
        except Exception:
            pass
        raise
    except Exception as e:
        logger.warning(f"Pub/sub wait failed for exam {exam_id}, falling back to polling: {e}")
        approval_received = await _poll_for_review(redis_client, redis_key, timeout_at)

    # Final check
    final_val = await redis_client.get(redis_key)
    if final_val is not None and approval_received is None:
        normalized = _normalize(final_val)
        if normalized == "true":
            approval_received = True
        elif normalized == "rejected":
            approval_received = False

    if approval_received is True:
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
        "checkpoint_2_feedback": None,
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
