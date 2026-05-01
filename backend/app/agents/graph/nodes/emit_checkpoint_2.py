"""emit_checkpoint_2 — Emit HITL Checkpoint 2 (full review) event."""

import logging

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit_async

logger = logging.getLogger("app.agents.graph")


async def emit_checkpoint_2(state: ExamGraphState) -> ExamGraphState:
    """
    Emit HITL Checkpoint 2: Full Review event.

    Sends the questions, validation_passed, issues, and warnings to the frontend.
    This is the main review checkpoint before final export.

    Also persists the session to ShortTermMemory (Redis) so that
    orchestrator.submit_review() can load it later for rejection/regeneration.

    Args:
        state: Must contain questions, validation_result, warnings.

    Returns:
        Updated state with checkpoint_2_status = PENDING.
    """
    from app.websocket.manager import get_connection_manager

    questions = state.get("questions", [])
    validation_result = state.get("validation_result", {})
    warnings = list(state.get("warnings", []))
    exam_id = state.get("exam_id", "")

    manager = get_connection_manager()
    await _emit_async(manager, exam_id, {
        "type": "hitl_checkpoint",
        "checkpoint_id": 2,
        "data": {
            "questions": questions,
            "validation_passed": validation_result.get("validation_passed", False),
            "issues": validation_result.get("issues", []),
            "warnings": warnings,
        },
    })

    # ── Persist session to Redis ShortTermMemory ────────────────────────────
    # submit_review loads this session to handle rejections and regeneration.
    user_id = state.get("user_id", "")
    if exam_id and user_id:
        try:
            from app.core.redis_client import get_redis_client
            from app.agents.memory.short_term import ShortTermMemory
            redis_client = get_redis_client()
            stm = ShortTermMemory(redis_client)
            await stm.save_session(
                exam_id, user_id,
                exam_config=state.get("exam_config", {}),
                exam_config_original=state.get("exam_config_original") or state.get("exam_config", {}),
                document_id=state.get("document_id"),
                scope=state.get("scope", []),
                topics_used=state.get("topics_used", []),
                retrieved_context=state.get("retrieved_context", []),
            )
            # Also save fields not in save_session signature via direct Redis merge
            session_key = stm._session_key(exam_id, user_id)
            existing = await stm.load_session(exam_id, user_id) or {}
            existing["questions"] = questions
            existing["cost_report"] = state.get("cost_report", {})
            existing["blueprint"] = state.get("blueprint", [])
            existing["retry_count"] = state.get("retry_count", 0)
            await redis_client.set_json(session_key, existing, ttl=7200)
            logger.info("Saved session to ShortTermMemory for exam %s at CP2", exam_id)
        except Exception as e:
            logger.warning("Failed to save session at CP2 for exam %s: %s", exam_id, e)

    return {
        **state,
        "checkpoint_2_status": HITLCheckpointStatus.PENDING,
        "current_step": 4,
    }

