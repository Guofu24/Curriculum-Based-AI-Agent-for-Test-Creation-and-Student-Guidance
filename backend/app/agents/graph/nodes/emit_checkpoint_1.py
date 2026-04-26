"""emit_checkpoint_1 — Emit HITL Checkpoint 1 (blueprint review) event."""

import logging

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit_async

logger = logging.getLogger("app.agents.graph")


async def emit_checkpoint_1(state: ExamGraphState) -> ExamGraphState:
    """
    Emit HITL Checkpoint 1: Blueprint Review event.

    Sends the blueprint and distribution_summary to the frontend via WebSocket.
    Events are awaited so they reach the frontend before the graph continues
    to wait_for_blueprint_approval. The graph then transitions to
    wait_for_blueprint_approval where execution pauses via interrupt().

    Args:
        state: Must contain blueprint, distribution_summary.

    Returns:
        Updated state with checkpoint_1_status = PENDING.
    """
    from app.websocket.manager import get_connection_manager

    blueprint = state.get("blueprint", [])
    distribution_summary = state.get("distribution_summary", {})
    exam_id = state.get("exam_id", "")
    warnings = list(state.get("warnings", []))

    logger.info(f"[emit_checkpoint_1] exam_id={exam_id}, blueprint_slots={len(blueprint)}, emitting hitl_checkpoint...")
    print(f"[emit_checkpoint_1] exam_id={exam_id}, blueprint_slots={len(blueprint)}, emitting hitl_checkpoint NOW!", flush=True)

    manager = get_connection_manager()
    await _emit_async(manager, exam_id, {
        "type": "hitl_checkpoint",
        "checkpoint_id": 1,
        "data": {
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
        },
    })
    await _emit_async(manager, exam_id, {
        "type": "plan_step",
        "message": "Đang chờ phê duyệt blueprint...",
        "step": 2,
        "total_steps": 5,
    })

    logger.info(f"[emit_checkpoint_1] exam_id={exam_id}, events emitted successfully")

    return {
        **state,
        "checkpoint_1_status": HITLCheckpointStatus.PENDING,
        "current_step": 2,
        "warnings": warnings,
    }

