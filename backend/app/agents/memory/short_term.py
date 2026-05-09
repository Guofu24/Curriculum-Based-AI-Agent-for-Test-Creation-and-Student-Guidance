"""Short-term memory (Redis): session:{exam_id}:{user_id} with TTL 7200s."""

import json
import logging
from typing import Any, Optional

from app.core.redis_client import RedisClient

logger = logging.getLogger("app.agents.memory")

# Short-term memory TTL: 2 hours
SHORT_TERM_TTL = 7200

# G9: Retry issues TTL: 1 hour
RETRY_ISSUES_TTL = 3600


class ShortTermMemory:
    """
    Short-term session memory stored in Redis.
    Key: session:{exam_id}:{user_id}, TTL 7200s (2 hours).

    G2 Methods:
        - save_session()
        - load_session()
        - append_history()
        - update_topics()
        - increment_retry()
        - save_retry_issues()   ← G9
        - load_retry_issues()  ← G9
    """

    def __init__(self, redis: RedisClient):
        self.redis: RedisClient = redis

    def _session_key(self, exam_id: str, user_id: str) -> str:
        """Session key format."""
        return f"session:{exam_id}:{user_id}"

    # ── G2 Methods ─────────────────────────────────────────────────────────────

    async def save_session(
        self,
        exam_id: str,
        user_id: str,
        exam_config: dict | None = None,
        topics_used: list[str] | None = None,
        # G2+: additional session fields
        exam_config_original: dict | None = None,
        conversation_history: list[dict] | None = None,
        retry_count: int | None = None,
        review_approved: bool | None = None,
        review_feedback: str | None = None,
        retrieved_context: list | None = None,
        scope: list | None = None,
        document_id: str | None = None,
    ) -> None:
        """
        Save or update a session in Redis — merges with existing data.
        G2: saves exam_config and topics_used for the session.
        Stores all fields passed as parameters (merges with existing).
        """
        existing: dict = {}
        try:
            existing = await self.load_session(exam_id, user_id) or {}
        except Exception as exc:
            logger.warning("ShortTermMemory: failed to load existing session %s: %s", exam_id, exc)

        if exam_config is not None:
            existing["exam_config"] = exam_config
        if topics_used is not None:
            existing["topics_used"] = topics_used
        if exam_config_original is not None:
            existing["exam_config_original"] = exam_config_original
        if conversation_history is not None:
            existing["conversation_history"] = conversation_history
        if retry_count is not None:
            existing["retry_count"] = retry_count
        if review_approved is not None:
            existing["review_approved"] = review_approved
        if review_feedback is not None:
            existing["review_feedback"] = review_feedback
        if retrieved_context is not None:
            existing["retrieved_context"] = retrieved_context
        if scope is not None:
            existing["scope"] = scope
        if document_id is not None:
            existing["document_id"] = document_id

        await self.redis.set_json(
            self._session_key(exam_id, user_id),
            existing,
            ttl=SHORT_TERM_TTL,
        )

    async def load_session(self, exam_id: str, user_id: str) -> dict | None:
        """Load a session from Redis. Returns None if not found."""
        return await self.redis.get_json(self._session_key(exam_id, user_id))

    async def append_history(
        self,
        exam_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        """
        Append a message to conversation history.
        G2: stores [role, content] entries.
        """
        session = await self.load_session(exam_id, user_id)
        if session is None:
            return

        history: list[dict] = session.get("conversation_history", [])
        history.append({"role": role, "content": content})
        session["conversation_history"] = history

        await self.redis.set_json(
            self._session_key(exam_id, user_id),
            session,
            ttl=SHORT_TERM_TTL,
        )

    async def update_topics(
        self,
        exam_id: str,
        user_id: str,
        new_topics: list[str],
    ) -> None:
        """Merge new_topics into the session's topics_used list. G2."""
        session = await self.load_session(exam_id, user_id)
        if session is None:
            return

        existing = set(session.get("topics_used", []))
        existing.update(new_topics)
        session["topics_used"] = list(existing)

        await self.redis.set_json(
            self._session_key(exam_id, user_id),
            session,
            ttl=SHORT_TERM_TTL,
        )

    async def increment_retry(self, exam_id: str, user_id: str) -> int:
        """
        Increment retry_count in session atomically using Redis INCR.
        Returns the new count.
        G9: used by validator retry loop. Uses atomic INCR to avoid race conditions.
        """
        key = f"retry_count:{exam_id}:{user_id}"
        new_count = await self.redis.client.incr(key)
        await self.redis.expire(key, SHORT_TERM_TTL)
        return int(new_count)

    async def get_retry_count(self, exam_id: str, user_id: str) -> int:
        """
        Load retry_count from the atomic counter key.
        Returns 0 if not found.
        G9: Used by orchestrator retry loop to track retry attempts.
        """
        key = f"retry_count:{exam_id}:{user_id}"
        val = await self.redis.client.get(key)
        if val is None:
            return 0
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    # ── G9 Methods ─────────────────────────────────────────────────────────────

    async def save_retry_issues(self, exam_id: str, issues: list[dict]) -> None:
        """
        Persist validator issues to Redis so they survive Celery worker restarts.
        Key: retry_issues:{exam_id}, TTL 3600s (1 hour).
        G9: Called by ValidatorAgent instead of storing in-memory.
        """
        key = f"retry_issues:{exam_id}"
        await self.redis.set_json(key, {"issues": issues}, ttl=RETRY_ISSUES_TTL)

    async def load_retry_issues(self, exam_id: str) -> list[dict]:
        """
        Load persisted retry issues from Redis.
        Key: retry_issues:{exam_id}, TTL 3600s.
        G9: Called by Orchestrator to pass issues back to Builder.
        Returns empty list if no issues found.
        """
        key = f"retry_issues:{exam_id}"
        data = await self.redis.get_json(key)
        if data is None:
            return []
        return data.get("issues", [])
