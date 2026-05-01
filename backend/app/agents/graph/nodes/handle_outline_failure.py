"""handle_outline_failure — Fatal error when outline creation fails."""

import logging

from app.agents.graph.state import ExamGraphState, PipelineStatus

logger = logging.getLogger("app.agents.graph")


async def handle_outline_failure(state: ExamGraphState) -> ExamGraphState:
    """
    Fatal error node: outline creation failed and cannot proceed.

    Stops the pipeline and sets critical_error so the frontend receives
    an error event.

    Args:
        state: Any state.

    Returns:
        Updated state with pipeline_status = FAILED and critical_error set.
    """
    warnings = list(state.get("warnings", []))

    return {
        **state,
        "pipeline_status": PipelineStatus.FAILED,
        "critical_error": "Outline creation failed — cannot proceed without a blueprint",
        "warnings": warnings + ["Outline creation failed"],
        "questions": [],
        "blueprint": [],
    }
