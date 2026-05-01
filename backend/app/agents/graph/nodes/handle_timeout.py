"""handle_timeout — Terminal node when a checkpoint times out."""

import logging

from app.agents.graph.state import ExamGraphState, PipelineStatus

logger = logging.getLogger("app.agents.graph")


async def handle_timeout(state: ExamGraphState) -> ExamGraphState:
    """
    Terminal node: HITL checkpoint timed out.

    The pipeline stops. The user can re-trigger generation manually.

    Args:
        state: Any state.

    Returns:
        Updated state with pipeline_status = FAILED and timeout error.
    """
    warnings = list(state.get("warnings", []))
    warnings.append("Pipeline stopped due to checkpoint timeout")

    return {
        **state,
        "pipeline_status": PipelineStatus.FAILED,
        "critical_error": "HITL checkpoint timeout — pipeline stopped",
        "warnings": warnings,
        "questions": [],
    }
