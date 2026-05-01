"""save_teacher_preferences — G14: Save preferences to long-term memory after approval."""

import logging
from uuid import UUID

from app.agents.graph.state import ExamGraphState
from app.agents.memory import LongTermMemory
from app.core.database import async_session_maker

logger = logging.getLogger("app.agents.graph")


async def save_teacher_preferences(state: ExamGraphState) -> ExamGraphState:
    """
    G14: Persist teacher preferences to long-term memory (PostgreSQL) after approval.

    Non-fatal: failures are logged but do not block the pipeline.

    Args:
        state: Must contain user_id, exam_config_original.

    Returns:
        Updated state with warnings (if save failed, warning is added).
    """
    warnings = list(state.get("warnings", []))

    if not state.get("checkpoint_2_approved"):
        return state  # Only save if approved

    exam_config = state.get("exam_config_original") or state.get("exam_config", {})

    try:
        async with async_session_maker() as db:
            long_term = LongTermMemory(db)
            user_uuid = UUID(state["user_id"])
            await long_term.save_preferences(
                user_id=user_uuid,
                preferred_bloom_distribution=exam_config.get("bloom_distribution"),
                preferred_exam_types={"types": [exam_config.get("exam_type", "mixed")]},
                subject_focus=",".join(exam_config.get("scope", [])),
            )
            warnings.append("Teacher preferences saved to long-term memory")
    except ValueError:
        warnings.append("Invalid user_id — cannot save teacher preferences")
    except Exception as exc:
        logger.warning("Failed to save teacher preferences: %s", exc)
        warnings.append(f"Failed to save teacher preferences: {exc}")

    return {
        **state,
        "warnings": warnings,
    }
