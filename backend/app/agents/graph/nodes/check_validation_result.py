"""check_validation_result — Conditional branch node (no-op routing)."""

from app.agents.graph.state import ExamGraphState

# This node is a routing-only node. It returns the state unchanged.
# The conditional edge _evaluate_validation() uses the state to decide the next node.


async def check_validation_result(state: ExamGraphState) -> ExamGraphState:
    """
    Routing node: checks validation result and lets conditional edges decide next step.

    Does not modify state. The graph edges handle the routing:
      - validation_passed → emit_checkpoint_2
      - needs_retry AND retry_count < max → retry_builder
      - max_exceeded → handle_max_retries_exceeded

    Args:
        state: Must contain validation_result, retry_count, retry_issues.

    Returns:
        The state unchanged.
    """
    return state
