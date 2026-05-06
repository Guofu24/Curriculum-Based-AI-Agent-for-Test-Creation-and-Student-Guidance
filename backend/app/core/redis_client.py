"""Redis client for caching and pub/sub."""

import json
import logging
import threading
from typing import Any, Optional
import redis.asyncio as redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Lazy pool — only created on first access to avoid connection errors at import time
_redis_pool: "redis.ConnectionPool | None" = None
_redis_available: bool = True


def _get_pool() -> redis.ConnectionPool:
    global _redis_pool, _redis_available
    if _redis_pool is None:
        settings = get_settings()
        try:
            _redis_pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=500,
                decode_responses=True,
            )
            _redis_available = True
        except Exception as exc:
            logger.warning("Failed to create Redis connection pool: %s", exc)
            _redis_available = False
            raise
    return _redis_pool


def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    pool = _get_pool()
    return redis.Redis(connection_pool=pool)


async def close_redis() -> None:
    """Close Redis connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.disconnect()
        _redis_pool = None


class RedisClient:
    """
    Redis wrapper with helper methods.

    Provides graceful degradation: if Redis is unavailable, operations
    silently fall back to an in-memory dict. A warning is logged once.
    """

    def __init__(self, client_or_url: "redis.Redis | str | None" = None):
        """Accept either a Redis client instance or a URL string."""
        self._using_fallback = False
        self._fallback: dict[str, Any] = {}
        self._fallback_lock = threading.Lock()

        if isinstance(client_or_url, str):
            import redis.asyncio as async_redis
            self.client: redis.Redis = async_redis.from_url(client_or_url)
        elif client_or_url is not None:
            self.client = client_or_url
        else:
            try:
                self.client = get_redis()
            except Exception:
                self._mark_fallback()
                self.client = None

    def _mark_fallback(self) -> None:
        global _redis_available
        if not self._using_fallback:
            self._using_fallback = True
            _redis_available = False
            logger.warning(
                "Redis unavailable — falling back to in-memory storage. "
                "Rate limiting, pub/sub, and event replay will be degraded."
            )

    def _check_fallback(self) -> None:
        """Mark fallback mode if Redis client is unavailable."""
        if self.client is None:
            self._mark_fallback()

    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        self._check_fallback()
        if self._using_fallback:
            with self._fallback_lock:
                val = self._fallback.get(key)
            if isinstance(val, str):
                return val
            return None
        try:
            return await self.client.get(key)
        except Exception as exc:
            logger.warning("Redis get(%s) failed: %s", key, exc)
            return None

    async def get_json(self, key: str) -> Optional[dict]:
        """Get JSON value by key."""
        value = await self.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return None

    async def set(
        self, key: str, value: str, ttl: Optional[int] = None
    ) -> None:
        """Set key-value pair with optional TTL."""
        self._check_fallback()
        if self._using_fallback:
            with self._fallback_lock:
                self._fallback[key] = value
            return
        await self.client.set(key, value)
        if ttl:
            await self.client.expire(key, ttl)

    async def set_json(
        self, key: str, value: dict, ttl: Optional[int] = None
    ) -> None:
        """Set JSON value with optional TTL."""
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl)

    async def delete(self, key: str) -> None:
        """Delete key."""
        self._check_fallback()
        if self._using_fallback:
            with self._fallback_lock:
                self._fallback.pop(key, None)
            return
        await self.client.delete(key)

    async def incr(self, key: str) -> int:
        """Increment counter."""
        self._check_fallback()
        if self._using_fallback:
            with self._fallback_lock:
                current = self._fallback.get(key, 0)
                new_val = current + 1
                self._fallback[key] = new_val
            return new_val
        return await self.client.incr(key)

    async def expire(self, key: str, ttl: int) -> None:
        """Set TTL on key (no-op in fallback mode)."""
        if self._using_fallback:
            return
        await self.client.expire(key, ttl)

    async def publish(self, channel: str, message: dict) -> None:
        """Publish message to channel (no-op in fallback mode)."""
        if self._using_fallback:
            logger.debug("Redis publish skipped (fallback mode): %s", channel)
            return
        await self.client.publish(channel, json.dumps(message, ensure_ascii=False))

    async def hset(self, name: str, key: str, value: str) -> None:
        """Set hash field."""
        self._check_fallback()
        if self._using_fallback:
            with self._fallback_lock:
                if name not in self._fallback:
                    self._fallback[name] = {}
                self._fallback[name][key] = value
            return
        await self.client.hset(name, key, value)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field."""
        self._check_fallback()
        if self._using_fallback:
            with self._fallback_lock:
                h = self._fallback.get(name, {})
                if isinstance(h, dict):
                    return h.get(key)
            return None
        return await self.client.hget(name, key)

    async def hgetall(self, name: str) -> dict:
        """Get all hash fields."""
        self._check_fallback()
        if self._using_fallback:
            with self._fallback_lock:
                val = self._fallback.get(name, {})
                return dict(val) if isinstance(val, dict) else {}
        return await self.client.hgetall(name)

    async def incr_rate_limit(self, key: str, window_seconds: int = 60) -> int:
        """Increment rate limit counter with TTL."""
        count = await self.incr(key)
        if count == 1:
            await self.expire(key, window_seconds)
        return count


_redis_client_instance: "RedisClient | None" = None


def get_redis_client() -> RedisClient:
    """Get Redis client wrapper, reusing existing async connection."""
    global _redis_client_instance
    if _redis_client_instance is None:
        _redis_client_instance = RedisClient(get_redis())
    return _redis_client_instance
