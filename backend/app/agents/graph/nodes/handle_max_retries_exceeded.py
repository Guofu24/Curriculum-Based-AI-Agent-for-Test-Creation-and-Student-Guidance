"""handle_max_retries_exceeded — G9: Validation still failing after max retries."""

import logging

from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


async def handle_max_retries_exceeded(state: ExamGraphState) -> ExamGraphState:
    """
    G9: Maximum retries exhausted — continue with current questions anyway.

    The pipeline does not stop. The user receives the questions with warnings
    and can still review them at HITL Checkpoint 2.

    Args:
        state: Any state.

    Returns:
        Updated state with warnings appended.
    """
    warnings = list(state.get("warnings", []))
    warnings.append("Validation did not pass after 3 retries — continuing with warnings")

    return {
        **state,
        "warnings": warnings,
    }
