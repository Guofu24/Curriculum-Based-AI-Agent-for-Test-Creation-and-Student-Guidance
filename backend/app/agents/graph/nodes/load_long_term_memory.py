"""load_long_term_memory — G3: Load teacher preferences from PostgreSQL."""

import logging
from uuid import UUID

from app.agents.graph.state import ExamGraphState
from app.agents.memory import LongTermMemory
from app.core.database import async_session_maker

logger = logging.getLogger("app.agents.graph")


async def load_long_term_memory(state: ExamGraphState) -> ExamGraphState:
    """
    G3: Load teacher preferences from long-term memory (PostgreSQL).

    Non-fatal: if loading fails, continues with empty prefs and adds a warning.

    Args:
        state: Must contain user_id.

    Returns:
        Updated ExamGraphState with teacher_prefs populated.
    """
    warnings = list(state.get("warnings", []))
    teacher_prefs = {}

    try:
        async with async_session_maker() as db:
            long_term = LongTermMemory(db)
            user_uuid = UUID(state["user_id"])
            prefs = await long_term.get_preferences(user_uuid)
            if prefs:
                teacher_prefs = prefs
                warnings.append("Loaded teacher preferences from long-term memory")
    except ValueError:
        warnings.append("Invalid user_id format — cannot load teacher preferences")
    except Exception as exc:
        logger.warning("Failed to load teacher preferences: %s", exc)
        warnings.append(f"Failed to load teacher preferences: {exc}")

    return {
        **state,
        "teacher_prefs": teacher_prefs,
        "warnings": warnings,
        "updated_at": state.get("updated_at"),
    }
