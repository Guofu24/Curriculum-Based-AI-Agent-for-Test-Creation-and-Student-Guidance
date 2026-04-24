"""emit_checkpoint_2 — Emit HITL Checkpoint 2 (full review) event."""

import logging

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def emit_checkpoint_2(state: ExamGraphState) -> ExamGraphState:
    """
    Emit HITL Checkpoint 2: Full Review event.

    Sends the questions, validation_passed, issues, and warnings to the frontend.
    This is the main review checkpoint before final export.

    Args:
        state: Must contain questions, validation_result, warnings.

    Returns:
        Updated state with checkpoint_2_status = PENDING.
    """
    questions = state.get("questions", [])
    validation_result = state.get("validation_result", {})
    warnings = list(state.get("warnings", []))

    _emit(state, {
        "type": "hitl_checkpoint",
        "checkpoint_id": 2,
        "data": {
            "questions": questions,
            "validation_passed": validation_result.get("validation_passed", False),
            "issues": validation_result.get("issues", []),
            "warnings": warnings,
        },
    })

    return {
        **state,
        "checkpoint_2_status": HITLCheckpointStatus.PENDING,
        "current_step": 4,
    }

