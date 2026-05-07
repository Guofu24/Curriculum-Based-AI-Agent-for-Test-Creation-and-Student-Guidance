"""finalize_with_feedback — Terminal node when exam is rejected at review."""

import logging
from uuid import UUID

from app.agents.graph.state import ExamGraphState, PipelineStatus

logger = logging.getLogger("app.agents.graph")


async def finalize_with_feedback(state: ExamGraphState) -> ExamGraphState:
    """
    Terminal node when the teacher rejects the exam at HITL Checkpoint 2.

    Records rejection feedback to long-term memory for teacher style learning.
    """
    feedback = state.get("checkpoint_2_feedback", "")
    warnings = list(state.get("warnings", []))
    warnings.append(f"Exam rejected at review: {feedback[:100] if feedback else 'no feedback'}")

    # Persist rejection feedback to long-term memory
    user_id_str = state.get("user_id", "")
    if feedback and user_id_str:
        try:
            from app.agents.memory import LongTermMemory
            from app.core.database import async_session_maker
            async with async_session_maker() as db:
                memory = LongTermMemory(db)
                await memory.record_rejection(UUID(user_id_str), feedback)
        except Exception as exc:
            logger.warning("Failed to record rejection feedback: %s", exc)

    return {
        **state,
        "pipeline_status": PipelineStatus.FAILED,
        "warnings": warnings,
        "questions": [],
    }
