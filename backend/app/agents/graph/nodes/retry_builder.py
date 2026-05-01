"""retry_builder — G9: Increment retry count and prepare for rebuild."""

import logging

from app.agents.graph.state import ExamGraphState, AgentRole
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def retry_builder(state: ExamGraphState) -> ExamGraphState:
    """
    G9: Prepare state for a retry of BuilderAgent.

    Increments retry_count and emits a validation_retry event.
    The graph self-loop edge then returns to validate_questions.

    Bug-009 fix in ShortTermMemory: increment_retry() now uses atomic Redis INCR
    instead of load → modify → set, preventing race conditions.

    Args:
        state: Must contain exam_id, user_id, retry_issues.

    Returns:
        Updated ExamGraphState with retry_count incremented.
    """
    from app.core.redis_client import get_redis_client
    redis_client = get_redis_client()
    exam_id = state.get("exam_id", "")
    user_id = state.get("user_id", "")
    retry_count = int(state.get("retry_count", 0)) + 1
    warnings = list(state.get("warnings", []))

    # Atomic retry count increment
    if redis_client and exam_id and user_id:
        try:
            from app.agents.memory import ShortTermMemory
            stm = ShortTermMemory(redis_client)
            retry_count = await stm.increment_retry(exam_id, user_id)
        except Exception as exc:
            logger.warning("Failed to increment retry count in Redis: %s", exc)
            retry_count = int(state.get("retry_count", 0)) + 1

    warnings.append(f"Validation issues found — retry {retry_count}/3")

    _emit(state, {
        "type": "validation_retry",
        "retry_count": retry_count,
        "max_retries": 3,
        "issues_count": len(state.get("retry_issues", [])),
    })

    return {
        **state,
        "retry_count": retry_count,
        "pipeline_status": "retry_loop",  # type: ignore
        "current_agent": AgentRole.BUILDER,
        "warnings": warnings,
        "updated_at": state.get("updated_at"),
    }

