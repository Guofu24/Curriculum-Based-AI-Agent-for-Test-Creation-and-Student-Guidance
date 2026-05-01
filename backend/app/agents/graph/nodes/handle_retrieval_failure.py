"""handle_retrieval_failure — Graceful degradation when retrieval fails."""

import logging

from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


async def handle_retrieval_failure(state: ExamGraphState) -> ExamGraphState:
    """
    When RetrievalAgent fails, proceed with empty context.

    Sets retrieved_context to [] and logs a warning. The pipeline continues
    so the user still gets a response (with reduced quality).

    Args:
        state: Any state.

    Returns:
        Updated state with empty retrieved_context and allowed_concepts.
    """
    warnings = list(state.get("warnings", []))
    warnings.append("Retrieval failed — proceeding with empty context")

    return {
        **state,
        "retrieved_context": [],
        "allowed_concepts": [],
        "warnings": warnings,
    }
