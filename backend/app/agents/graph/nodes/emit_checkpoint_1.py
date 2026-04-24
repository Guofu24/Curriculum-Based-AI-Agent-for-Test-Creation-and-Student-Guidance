"""emit_checkpoint_1 — Emit HITL Checkpoint 1 (blueprint review) event."""

import logging

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def emit_checkpoint_1(state: ExamGraphState) -> ExamGraphState:
    """
    Emit HITL Checkpoint 1: Blueprint Review event.

    Sends the blueprint and distribution_summary to the frontend via WebSocket.
    The graph then transitions to wait_for_blueprint_approval.

    Args:
        state: Must contain blueprint, distribution_summary.

    Returns:
        Updated state with checkpoint_1_status = PENDING.
    """
    blueprint = state.get("blueprint", [])
    distribution_summary = state.get("distribution_summary", {})
    exam_id = state.get("exam_id", "")
    warnings = list(state.get("warnings", []))

    _emit(state, {
        "type": "hitl_checkpoint",
        "checkpoint_id": 1,
        "data": {
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
        },
    })

    _emit(state, {
        "type": "plan_step",
        "message": "Đang chờ phê duyệt blueprint...",
        "step": 2,
        "total_steps": 5,
    })

    return {
        **state,
        "checkpoint_1_status": HITLCheckpointStatus.PENDING,
        "current_step": 2,
        "warnings": warnings,
    }

