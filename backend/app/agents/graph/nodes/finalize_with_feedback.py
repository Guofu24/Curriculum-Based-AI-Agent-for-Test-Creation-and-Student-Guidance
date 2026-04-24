"""finalize_with_feedback — Terminal node when exam is rejected at review."""

import logging

from app.agents.graph.state import ExamGraphState, PipelineStatus

logger = logging.getLogger("app.agents.graph")


async def finalize_with_feedback(state: ExamGraphState) -> ExamGraphState:
    """
    Terminal node when the teacher rejects the exam at HITL Checkpoint 2.

    Logs the rejection feedback. The Celery task will dispatch a new generation
    task based on the feedback.

    Args:
        state: Must contain checkpoint_2_feedback.

    Returns:
        Updated state with pipeline_status = FAILED and feedback recorded.
    """
    feedback = state.get("checkpoint_2_feedback", "")
    warnings = list(state.get("warnings", []))
    warnings.append(f"Exam rejected at review: {feedback[:100] if feedback else 'no feedback'}")

    return {
        **state,
        "pipeline_status": PipelineStatus.FAILED,
        "warnings": warnings,
        "questions": [],
    }
