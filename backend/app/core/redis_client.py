"""Redis client for caching and pub/sub."""

import json
from typing import Any, Optional
import redis.asyncio as redis

from app.core.config import get_settings

settings = get_settings()

# Redis connection pool
redis_pool: redis.ConnectionPool = redis.ConnectionPool.from_url(
    settings.REDIS_URL,
    max_connections=20,
    decode_responses=True,
)


def get_redis() -> redis.Redis:
    """Get Redis client instance."""
    return redis.Redis(connection_pool=redis_pool)


async def close_redis() -> None:
    """Close Redis connection pool."""
    await redis_pool.disconnect()


class RedisClient:
    """Redis wrapper with helper methods."""

    def __init__(self, client_or_url: "redis.Redis | str | None" = None):
        """Accept either a Redis client instance or a URL string."""
        if isinstance(client_or_url, str):
            import redis.asyncio as async_redis
            self.client: redis.Redis = async_redis.from_url(client_or_url)
        elif client_or_url is not None:
            self.client = client_or_url
        else:
            self.client = get_redis()

    async def get(self, key: str) -> Optional[str]:
        """Get value by key."""
        return await self.client.get(key)

    async def get_json(self, key: str) -> Optional[dict]:
        """Get JSON value by key."""
        value = await self.get(key)
        if value:
            return json.loads(value)
        return None

    async def set(
        self, key: str, value: str, ttl: Optional[int] = None
    ) -> None:
        """Set key-value pair with optional TTL."""
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
        await self.client.delete(key)

    async def incr(self, key: str) -> int:
        """Increment counter."""
        return await self.client.incr(key)

    async def expire(self, key: str, ttl: int) -> None:
        """Set TTL on key."""
        await self.client.expire(key, ttl)

    async def publish(self, channel: str, message: dict) -> None:
        """Publish message to channel."""
        await self.client.publish(channel, json.dumps(message, ensure_ascii=False))

    async def hset(self, name: str, key: str, value: str) -> None:
        """Set hash field."""
        await self.client.hset(name, key, value)

    async def hget(self, name: str, key: str) -> Optional[str]:
        """Get hash field."""
        return await self.client.hget(name, key)

    async def hgetall(self, name: str) -> dict:
        """Get all hash fields."""
        return await self.client.hgetall(name)

    async def incr_rate_limit(self, key: str, window_seconds: int = 60) -> int:
        """Increment rate limit counter with TTL."""
        count = await self.incr(key)
        if count == 1:
            await self.expire(key, window_seconds)
        return count


def get_redis_client() -> RedisClient:
    """Get Redis client wrapper."""
    return RedisClient(get_redis())
