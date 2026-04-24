"""wait_for_blueprint_approval — HITL Checkpoint 1: wait for blueprint approval via Redis pub/sub."""

import asyncio
import json
import logging
import time

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit

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


async def wait_for_blueprint_approval(state: ExamGraphState) -> ExamGraphState:
    """
    HITL Checkpoint 1: wait for blueprint approval via Redis pub/sub.

    This node implements a HITL (Human-In-The-Loop) checkpoint:
      1. Emit pipeline_paused + hitl_checkpoint events so the frontend shows the approval UI
      2. If Redis is unavailable → return PENDING immediately (non-blocking)
         This allows the FastAPI event loop to remain free so HTTP approve/reject
         requests can be processed by the same process.
      3. If Redis is available → poll until approval/rejection/timeout

    Args:
        state: Must contain exam_id, blueprint, checkpoint_1_timeout_at.

    Returns:
        Updated state with checkpoint_1_status set:
          - PENDING: Redis unavailable, frontend must poll or use HTTP endpoint
          - APPROVED: User approved the blueprint
          - REJECTED: User rejected or timeout
    """
    exam_id = state.get("exam_id", "")
    current_time = time.time()
    timeout_at = state.get("checkpoint_1_timeout_at") or (current_time + HITL_CHECKPOINT_1_TIMEOUT)
    redis_key = f"hitl:approved:{exam_id}:1"

    # ── Emit waiting event FIRST (critical for frontend) ──────────────────────────
    blueprint = state.get("blueprint", [])
    distribution_summary = state.get("distribution_summary", {})
    _emit(state, {
        "type": "pipeline_paused",
        "checkpoint_id": 1,
        "message": "Chờ phê duyệt blueprint...",
        "blueprint": blueprint,
        "distribution_summary": distribution_summary,
    })
    _emit(state, {
        "type": "hitl_checkpoint",
        "checkpoint_id": 1,
        "data": {
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
        },
    })

    # ── Check Redis availability ─────────────────────────────────────────────────
    redis_client = None
    try:
        from app.core.redis_client import get_redis_client
        redis_client = get_redis_client()
        await asyncio.wait_for(redis_client.client.ping(), timeout=2.0)
    except Exception as e:
        logger.warning(f"Redis unavailable for HITL checkpoint 1: {e}. "
                      "Returning PENDING — frontend must use HTTP approve endpoint.")
        _emit(state, {
            "type": "plan_step",
            "message": "Đang chờ phê duyệt blueprint...",
            "step": 2,
            "total_steps": 5,
        })
        return {
            **state,
            "checkpoint_1_approved": None,
            "checkpoint_1_status": HITLCheckpointStatus.PENDING,
            "pipeline_status": "paused",
        }

    # ── Redis available: poll for approval/rejection/timeout ─────────────────────
    channel = f"exam:{exam_id}"
    approval_received: bool | None = None

    try:
        sub = redis_client.client.pubsub()
        await sub.subscribe(channel)
        logger.info(f"Subscribed to Redis channel '{channel}', waiting for blueprint approval...")

        start_time = time.time()
        last_progress_emit = start_time

        while approval_received is None:
            elapsed = time.time() - start_time
            remaining = timeout_at - time.time()

            if elapsed - last_progress_emit >= 30.0:
                _emit(state, {
                    "type": "plan_step",
                    "message": f"Đang chờ phê duyệt blueprint... ({int(remaining // 60)}m còn lại)",
                    "step": 2,
                    "total_steps": 5,
                })
                last_progress_emit = elapsed

            if remaining <= 0:
                logger.warning(f"Blueprint approval timeout for exam {exam_id}")
                break

            # Check Redis key
            try:
                val = await asyncio.wait_for(redis_client.get(redis_key), timeout=0.5)
                if val is not None:
                    normalized = _normalize(val)
                    if normalized == "true":
                        approval_received = True
                        break
                    if normalized == "rejected":
                        approval_received = False
                        break
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass

            # Wait for pub/sub message
            try:
                msg = await asyncio.wait_for(
                    sub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=1.0
                )
                if msg and msg.get("type") == "message":
                    data = msg.get("data", "")
                    try:
                        event = json.loads(data) if isinstance(data, str) else data
                        event_type = event.get("type", "") if isinstance(event, dict) else ""
                        if event_type in ("blueprint_approved", "hitl_approved"):
                            approval_received = True
                            break
                        if event_type in ("blueprint_rejected", "hitl_rejected"):
                            approval_received = False
                            break
                    except Exception:
                        pass
            except asyncio.TimeoutError:
                pass
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
        approval_received = await _poll_for_approval(redis_client, redis_key, timeout_at)

    # Final Redis key check
    if approval_received is None:
        try:
            final_val = await redis_client.get(redis_key)
            if final_val is not None:
                normalized = _normalize(final_val)
                if normalized == "true":
                    approval_received = True
                elif normalized == "rejected":
                    approval_received = False
        except Exception:
            pass

    # ── Process result ───────────────────────────────────────────────────────────
    if approval_received is True:
        _emit(state, {"type": "blueprint_approved_received", "exam_id": exam_id})
        return {
            **state,
            "checkpoint_1_approved": True,
            "checkpoint_1_status": HITLCheckpointStatus.APPROVED,
            "pipeline_status": "running",
        }

    history = list(state.get("checkpoint_1_rejection_history", []))
    rejection_data = state.get("_last_rejection", {})
    if rejection_data:
        history.append({
            "feedback": rejection_data.get("feedback", ""),
            "timestamp": rejection_data.get("timestamp", time.time()),
        })

    _emit(state, {
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


async def _poll_for_approval(
    redis_client,
    redis_key: str,
    timeout_at: float,
) -> bool | None:
    """Fallback polling when pub/sub fails."""
    interval = 3.0
    while time.time() < timeout_at:
        try:
            val = await asyncio.wait_for(redis_client.get(redis_key), timeout=interval)
            if val is not None:
                normalized = _normalize(val)
                if normalized == "true":
                    return True
                if normalized == "rejected":
                    return False
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass
        await asyncio.sleep(interval)
    return None
