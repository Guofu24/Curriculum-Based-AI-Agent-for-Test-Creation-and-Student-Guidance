"""Shared Gemini API key cooldown pool.

The parser, alignment router, and future Gemini-backed jobs should all read the
same Redis cooldown namespace so a key that just parsed a PDF is not immediately
reused for another burst of requests.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Iterable

from app.core.config import get_settings
from app.core.redis_client import RedisClient

logger = logging.getLogger("app.rag.gemini_key_pool")

COOLDOWN_TTL_SECONDS: dict[str, int] = {
    "recent_use": 30,
    "parser_recent_use": 300,
    "alignment_recent_use": 30,
    "503": 60,
    "429": 300,
}
DAILY_QUOTA_TTL_SECONDS = 26 * 60 * 60
DISABLED_TTL_SECONDS = 30 * 24 * 60 * 60


def _key_hash(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _cooldown_key(api_key: str) -> str:
    return f"gemini_cooldown:{_key_hash(api_key)}"


def _disabled_key(api_key: str) -> str:
    return f"gemini_disabled:{_key_hash(api_key)}"


def _classify_error(error: BaseException | str) -> str:
    text = str(error).lower()
    if "429" in text or "quota" in text or "resource_exhausted" in text or "rate limit" in text:
        if (
            "perday" in text
            or "per day" in text
            or "requestsperday" in text
            or "generaterequestsperday" in text
            or "generate_content_free_tier_requests" in text
        ):
            return "daily_quota"
        return "429"
    if "403" in text or "permission" in text or "denied" in text:
        return "invalid"
    if "400" in text or "invalid api key" in text or "api key not valid" in text:
        return "invalid"
    if "503" in text or "500" in text or "overload" in text or "unavailable" in text:
        return "503"
    return "recent_use"


class GeminiKeyPool:
    """Redis-backed Gemini key selector with cooldown and disabled-key support."""

    def __init__(
        self,
        redis: RedisClient | None = None,
        keys: Iterable[str] | None = None,
    ) -> None:
        self.redis = redis or RedisClient()
        self.keys = [k.strip() for k in (keys or get_settings().GEMINI_KEYS) if k and k.strip()]
        self._cursor = 0

    @property
    def has_keys(self) -> bool:
        return bool(self.keys)

    async def get_available_key(
        self,
        *,
        allow_cooldown: bool = False,
        exclude: Iterable[str] | None = None,
        blocked_cooldown_reasons: Iterable[str] | None = None,
    ) -> str | None:
        """Return the next usable key.

        By default this avoids recently-used keys so parser/alignment bursts do
        not immediately reuse the same project quota. Callers may opt into
        cooldown keys as a fallback after fresh keys are exhausted.
        """
        if not self.keys:
            return None

        excluded = set(exclude or ())
        blocked_reasons = set(blocked_cooldown_reasons or ())
        total = len(self.keys)
        for offset in range(total):
            idx = (self._cursor + offset) % total
            key = self.keys[idx]
            if key in excluded:
                continue
            disabled = await self.redis.get(_disabled_key(key))
            if disabled:
                continue
            cooldown = await self.redis.get(_cooldown_key(key))
            if cooldown:
                if cooldown in blocked_reasons:
                    continue
                if not allow_cooldown:
                    continue
            self._cursor = (idx + 1) % total
            return key
        return None

    async def mark_used(self, api_key: str, source: str = "") -> None:
        reason = f"{source}_recent_use" if source else "recent_use"
        await self.mark_cooldown(api_key, reason)

    async def mark_cooldown(self, api_key: str, reason: str) -> None:
        if not api_key:
            return
        if reason == "invalid":
            await self.mark_disabled(api_key, reason, DISABLED_TTL_SECONDS)
            return
        if reason == "daily_quota":
            await self.mark_disabled(api_key, reason, DAILY_QUOTA_TTL_SECONDS)
            return
        ttl = COOLDOWN_TTL_SECONDS.get(reason, COOLDOWN_TTL_SECONDS["recent_use"])
        await self.redis.set(_cooldown_key(api_key), reason, ttl=ttl)
        logger.debug("Gemini key %s cooldown=%s ttl=%ss", _key_hash(api_key), reason, ttl)

    async def mark_disabled(
        self,
        api_key: str,
        reason: str = "invalid",
        ttl: int = DISABLED_TTL_SECONDS,
    ) -> None:
        if not api_key:
            return
        await self.redis.set(_disabled_key(api_key), reason, ttl=ttl)
        logger.warning(
            "Gemini key %s disabled for %ss: %s",
            _key_hash(api_key),
            ttl,
            reason,
        )

    async def mark_error(self, api_key: str, error: BaseException | str) -> None:
        await self.mark_cooldown(api_key, _classify_error(error))


def _sync_set_key(name: str, value: str, ttl: int) -> None:
    """Best-effort sync Redis write for parser worker threads."""
    try:
        import redis

        client = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        client.set(name, value, ex=ttl)
        client.close()
    except Exception as exc:  # pragma: no cover - parser must not fail on Redis
        logger.debug("Gemini cooldown sync write skipped: %s", exc)


def mark_gemini_key_used_sync(api_key: str, source: str = "parser") -> None:
    if api_key:
        reason = f"{source}_recent_use" if source else "recent_use"
        _sync_set_key(_cooldown_key(api_key), reason, COOLDOWN_TTL_SECONDS.get(reason, COOLDOWN_TTL_SECONDS["recent_use"]))


def mark_gemini_key_error_sync(api_key: str, error: BaseException | str) -> None:
    if not api_key:
        return
    reason = _classify_error(error)
    if reason == "invalid":
        _sync_set_key(_disabled_key(api_key), "invalid", DISABLED_TTL_SECONDS)
        return
    if reason == "daily_quota":
        _sync_set_key(_disabled_key(api_key), "daily_quota", DAILY_QUOTA_TTL_SECONDS)
        return
    _sync_set_key(_cooldown_key(api_key), reason, COOLDOWN_TTL_SECONDS.get(reason, 30))
