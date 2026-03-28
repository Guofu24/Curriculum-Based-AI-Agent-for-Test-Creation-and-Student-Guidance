"""Memory Layer: short-term (Redis) and long-term (PostgreSQL)."""

from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.teacher_preference import TeacherPreference
from app.core.redis_client import RedisClient

# Short-term memory TTL: 2 hours
SHORT_TERM_TTL = 7200


class ShortTermMemory:
    """
    Short-term session memory stored in Redis.
    Key: session:{exam_id}:{user_id}
    TTL: 2 hours
    """

    def __init__(self, redis: RedisClient):
        self.redis = redis

    def _key(self, exam_id: str, user_id: str) -> str:
        return f"session:{exam_id}:{user_id}"

    async def save_session(
        self,
        exam_id: str,
        user_id: str,
        exam_config_original: dict,
        topics_used: list[str] | None = None,
        conversation_history: list[dict] | None = None,
        retry_count: int = 0,
    ) -> None:
        """Save or update a session in Redis."""
        data = {
            "exam_config_original": exam_config_original,
            "topics_used": topics_used or [],
            "conversation_history": conversation_history or [],
            "retry_count": retry_count,
        }
        await self.redis.set_json(
            self._key(exam_id, user_id),
            data,
            ttl=SHORT_TERM_TTL,
        )

    async def load_session(self, exam_id: str, user_id: str) -> dict | None:
        """Load a session from Redis."""
        return await self.redis.get_json(self._key(exam_id, user_id))

    async def append_history(
        self,
        exam_id: str,
        user_id: str,
        role: str,  # "user" or "assistant"
        content: str,
    ) -> None:
        """Append a message to conversation history."""
        session = await self.load_session(exam_id, user_id)
        if session is None:
            return

        history = session.get("conversation_history", [])
        history.append({"role": role, "content": content})
        session["conversation_history"] = history

        await self.redis.set_json(
            self._key(exam_id, user_id),
            session,
            ttl=SHORT_TERM_TTL,
        )

    async def update_topics(
        self,
        exam_id: str,
        user_id: str,
        topics_used: list[str],
    ) -> None:
        """Update the topics_used list."""
        session = await self.load_session(exam_id, user_id)
        if session is None:
            return

        existing = set(session.get("topics_used", []))
        existing.update(topics_used)
        session["topics_used"] = list(existing)

        await self.redis.set_json(
            self._key(exam_id, user_id),
            session,
            ttl=SHORT_TERM_TTL,
        )

    async def increment_retry(self, exam_id: str, user_id: str) -> int:
        """Increment retry count and return new value."""
        session = await self.load_session(exam_id, user_id)
        if session is None:
            retry_count = 1
        else:
            retry_count = session.get("retry_count", 0) + 1

        if session:
            session["retry_count"] = retry_count
            await self.redis.set_json(
                self._key(exam_id, user_id),
                session,
                ttl=SHORT_TERM_TTL,
            )

        return retry_count

    async def get_retry_count(self, exam_id: str, user_id: str) -> int:
        """Get current retry count."""
        session = await self.load_session(exam_id, user_id)
        if session is None:
            return 0
        return session.get("retry_count", 0)

    async def delete_session(self, exam_id: str, user_id: str) -> None:
        """Delete a session."""
        await self.redis.delete(self._key(exam_id, user_id))

    async def extend_ttl(self, exam_id: str, user_id: str, ttl: int = SHORT_TERM_TTL) -> None:
        """Extend session TTL."""
        await self.redis.expire(self._key(exam_id, user_id), ttl)


class LongTermMemory:
    """
    Long-term memory stored in PostgreSQL.
    Persists teacher preferences across sessions.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_preferences(self, user_id: UUID) -> dict | None:
        """Load teacher preferences from PostgreSQL."""
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
        """Save or update teacher preferences."""
        result = await self.db.execute(
            select(TeacherPreference).where(TeacherPreference.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()

        if prefs:
            # Update existing
            if preferred_bloom_distribution is not None:
                prefs.preferred_bloom_distribution = preferred_bloom_distribution
            if preferred_exam_types is not None:
                prefs.preferred_exam_types = preferred_exam_types
            if subject_focus is not None:
                prefs.subject_focus = subject_focus
            if style_notes is not None:
                prefs.style_notes = style_notes
        else:
            # Create new
            prefs = TeacherPreference(
                user_id=user_id,
                preferred_bloom_distribution=preferred_bloom_distribution,
                preferred_exam_types=preferred_exam_types,
                subject_focus=subject_focus,
                style_notes=style_notes,
            )
            self.db.add(prefs)

        await self.db.commit()

    async def update_from_exam(
        self,
        user_id: UUID,
        exam_config: dict,
    ) -> None:
        """
        Update preferences based on an exam's config.
        Called after an exam is published to learn teacher preferences.
        """
        bloom_dist = exam_config.get("bloom_distribution", {})
        exam_type = exam_config.get("exam_type", "mixed")

        # Get current prefs
        current = await self.get_preferences(user_id)

        # Update preferred bloom distribution (weighted average with existing)
        if current and current.get("preferred_bloom_distribution"):
            existing = current["preferred_bloom_distribution"]
            # Simple update - could be more sophisticated
            new_dist = {
                "nhan_biet": bloom_dist.get("nhan_biet", 20),
                "thong_hieu": bloom_dist.get("thong_hieu", 30),
                "van_dung": bloom_dist.get("van_dung", 30),
                "van_dung_cao": bloom_dist.get("van_dung_cao", 20),
            }
        else:
            new_dist = bloom_dist

        await self.save_preferences(
            user_id=user_id,
            preferred_bloom_distribution=new_dist,
            preferred_exam_types={"mixed": 0.5, "mcq": 0.3, "essay": 0.2},
        )
