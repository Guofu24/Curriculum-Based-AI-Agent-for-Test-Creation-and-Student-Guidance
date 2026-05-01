"""handle_builder_failure — Graceful degradation when builder fails."""

import logging

from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


async def handle_builder_failure(state: ExamGraphState) -> ExamGraphState:
    """
    When BuilderAgent fails, continue to HITL Checkpoint 2 with partial questions.

    The pipeline does not stop — the user will see partial results with a warning.

    Args:
        state: Any state with questions.

    Returns:
        Updated state with warnings appended.
    """
    warnings = list(state.get("warnings", []))
    warnings.append("Builder had issues generating questions — continuing with partial results")

    return {
        **state,
        "warnings": warnings,
    }
