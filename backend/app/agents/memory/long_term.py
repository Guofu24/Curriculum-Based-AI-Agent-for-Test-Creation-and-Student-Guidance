"""Long-term memory (PostgreSQL): teacher preferences per user."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teacher_preference import TeacherPreference

_TOPIC_HISTORY_CAP = 200
_REJECT_PATTERNS_CAP = 20


class LongTermMemory:
    """
    Long-term memory stored in PostgreSQL.
    Persists teacher preferences and episodic history across sessions.
    """

    def __init__(self, db: AsyncSession):
        self.db: AsyncSession = db

    async def get_preferences(self, user_id: UUID) -> dict | None:
        """Load teacher preferences + episodic history from PostgreSQL."""
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
            "topic_history": prefs.topic_history or [],
            "reject_patterns": prefs.reject_patterns or [],
        }

    async def save_preferences(
        self,
        user_id: UUID,
        preferred_bloom_distribution: dict | None = None,
        preferred_exam_types: dict | None = None,
        subject_focus: str | None = None,
        style_notes: str | None = None,
    ) -> None:
        """Save or update teacher preferences (upsert)."""
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

    async def update_from_exam(self, user_id: UUID, exam_config: dict, questions: list[dict] | None = None) -> None:
        """
        G14: Extract preferences from an approved exam and save to long-term memory.
        Also appends question topics to topic_history for cross-exam dedup.
        """
        bloom_dist = exam_config.get("bloom_distribution")
        exam_type = exam_config.get("exam_type")
        scope = exam_config.get("scope", [])
        user_prompt = exam_config.get("user_prompt", "")

        result = await self.db.execute(
            select(TeacherPreference).where(TeacherPreference.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()

        if not prefs:
            prefs = TeacherPreference(user_id=user_id)
            self.db.add(prefs)

        if bloom_dist is not None:
            prefs.preferred_bloom_distribution = bloom_dist
        if exam_type:
            prefs.preferred_exam_types = {"types": [exam_type]}
        if scope:
            prefs.subject_focus = ",".join(scope)[:100]
        if user_prompt:
            prefs.style_notes = user_prompt[:500]

        # Append new topics to history, capped at _TOPIC_HISTORY_CAP
        if questions:
            new_topics = [
                q.get("topic_hint") or q.get("chapter") or ""
                for q in questions
                if q.get("topic_hint") or q.get("chapter")
            ]
            existing = list(prefs.topic_history or [])
            merged = existing + new_topics
            prefs.topic_history = merged[-_TOPIC_HISTORY_CAP:]

        await self.db.commit()

    async def record_rejection(self, user_id: UUID, feedback: str) -> None:
        """
        Record a teacher's rejection feedback for learning style patterns.
        Appended to reject_patterns, capped at _REJECT_PATTERNS_CAP entries.
        """
        if not feedback or not feedback.strip():
            return

        result = await self.db.execute(
            select(TeacherPreference).where(TeacherPreference.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()

        if not prefs:
            prefs = TeacherPreference(user_id=user_id)
            self.db.add(prefs)

        existing = list(prefs.reject_patterns or [])
        existing.append(feedback.strip()[:300])
        prefs.reject_patterns = existing[-_REJECT_PATTERNS_CAP:]

        await self.db.commit()
