"""emit_checkpoint_3 — Emit HITL Checkpoint 3 (export preview) event."""

import logging

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit_async

logger = logging.getLogger("app.agents.graph")


async def emit_checkpoint_3(state: ExamGraphState) -> ExamGraphState:
    """
    Emit HITL Checkpoint 3: Export Preview event.

    Sends the final questions, blueprint, distribution_summary, and cost_report.
    This is the last checkpoint before the pipeline ends.

    Args:
        state: Must contain exam_id, questions, blueprint,
               distribution_summary, cost_report.

    Returns:
        Updated state with checkpoint_3_status = PENDING.
    """
    from app.websocket.manager import get_connection_manager

    questions = state.get("questions", [])
    blueprint = state.get("blueprint", [])
    distribution_summary = state.get("distribution_summary", {})
    cost_report = state.get("cost_report", {})
    exam_id = state.get("exam_id", "")

    manager = get_connection_manager()
    await _emit_async(manager, exam_id, {
        "type": "hitl_checkpoint",
        "checkpoint_id": 3,
        "data": {
            "exam_id": exam_id,
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
            "questions": questions,
            "cost_report": cost_report,
        },
    })

    return {
        **state,
        "checkpoint_3_status": HITLCheckpointStatus.PENDING,
    }

