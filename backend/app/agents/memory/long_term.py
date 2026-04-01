"""Long-term memory (PostgreSQL): teacher preferences per user."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teacher_preference import TeacherPreference


class LongTermMemory:
    """
    Long-term memory stored in PostgreSQL.
    Persists teacher preferences across sessions.

    G3 Methods:
        - get_preferences(user_id) → TeacherPreference dict | None
        - save_preferences(user_id, prefs) → upsert after exam approve (G14)
    """

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    async def get_preferences(self, user_id: UUID) -> dict | None:
        """
        Load teacher preferences from PostgreSQL.
        G3: Returns None if no preferences exist for the user.
        """
        result = await self.db.execute(
            select(TeacherPreference).where(TeacherPreference.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()

        if not prefs:
            return None

        return {
            "preferred_bloom_distribution": prefs.preferred_bloom_distribution,
            "preferred_exam_types": prefs.preferred_exam_types,
            "subject_focus": prefs.subject_focus,
            "style_notes": prefs.style_notes,
        }

    async def save_preferences(
        self,
        user_id: UUID,
        preferred_bloom_distribution: dict | None = None,
        preferred_exam_types: dict | None = None,
        subject_focus: str | None = None,
        style_notes: str | None = None,
    ) -> None:
        """
        Save or update teacher preferences (upsert).
        G14: Only called AFTER user approves the exam blueprint.
        """
        result = await self.db.execute(
            select(TeacherPreference).where(TeacherPreference.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()

        if prefs:
            if preferred_bloom_distribution is not None:
                prefs.preferred_bloom_distribution = preferred_bloom_distribution
            if preferred_exam_types is not None:
                prefs.preferred_exam_types = preferred_exam_types
            if subject_focus is not None:
                prefs.subject_focus = subject_focus
            if style_notes is not None:
                prefs.style_notes = style_notes
        else:
            prefs = TeacherPreference(
                user_id=user_id,
                preferred_bloom_distribution=preferred_bloom_distribution,
                preferred_exam_types=preferred_exam_types,
                subject_focus=subject_focus,
                style_notes=style_notes,
            )
            self.db.add(prefs)

        await self.db.commit()

    async def update_from_exam(self, user_id: UUID, exam_config: dict) -> None:
        """
        G14: Extract preferences from an approved exam config and save to long-term memory.
        Convenience wrapper around save_preferences() that parses exam_config dict.
        Called by ExamService.publish_exam() when teacher approves an exam.
        """
        bloom_dist = exam_config.get("bloom_distribution")
        exam_type = exam_config.get("exam_type")
        scope = exam_config.get("scope", [])
        user_prompt = exam_config.get("user_prompt", "")

        await self.save_preferences(
            user_id=user_id,
            preferred_bloom_distribution=bloom_dist,
            preferred_exam_types={"types": [exam_type]} if exam_type else None,
            subject_focus=",".join(scope) if scope else None,
            style_notes=user_prompt[:500] if user_prompt else None,
        )
