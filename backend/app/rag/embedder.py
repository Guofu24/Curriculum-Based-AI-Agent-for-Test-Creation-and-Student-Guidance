"""Embedding service with Redis caching."""

from typing import Any
import hashlib
import json

from app.core.config import get_settings
from app.core.redis_client import RedisClient

settings = get_settings()

# Token pricing (approximate, per 1M tokens)
TOKEN_PRICING = {
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},  # per 1M tokens
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


class EmbeddingService:
    """Service for generating embeddings with Redis caching."""

    def __init__(self, redis: RedisClient | None = None):
        self.redis = redis
        self._client = None

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        if self.redis:
            cache_key = f"embed:{self._hash_text(text)}"
            cached = await self.redis.get_json(cache_key)
            if cached:
                return cached["embedding"]

        embedding = await self._call_embedding_api(text)

        if self.redis:
            cache_key = f"embed:{self._hash_text(text)}"
            await self.redis.set_json(
                cache_key,
                {"embedding": embedding},
                ttl=settings.EMBEDDING_CACHE_TTL_SECONDS,
            )

        return embedding

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in batch."""
        embeddings = []

        # Check cache for each text
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            if self.redis:
                cache_key = f"embed:{self._hash_text(text)}"
                cached = await self.redis.get_json(cache_key)
                if cached:
                    embeddings.append(cached["embedding"])
                    continue

            uncached_indices.append(i)
            uncached_texts.append(text)
            embeddings.append([])  # Placeholder

        # Batch embed uncached texts
        if uncached_texts:
            new_embeddings = await self._call_embedding_api_batch(uncached_texts)

            for idx, emb in zip(uncached_indices, new_embeddings):
                embeddings[idx] = emb

            # Cache results
            if self.redis:
                for text, emb in zip(uncached_texts, new_embeddings):
                    cache_key = f"embed:{self._hash_text(text)}"
                    await self.redis.set_json(
                        cache_key,
                        {"embedding": emb},
                        ttl=settings.EMBEDDING_CACHE_TTL_SECONDS,
                    )

        return embeddings

    async def _call_embedding_api(self, text: str) -> list[float]:
        """Call OpenAI embedding API."""
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            # Fallback: use deterministic hash-based embedding
            return self._fallback_embedding(text)

    async def _call_embedding_api_batch(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI embedding API for batch."""
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.embeddings.create(
                model=settings.OPENAI_EMBEDDING_MODEL,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception:
            return [self._fallback_embedding(t) for t in texts]

    def _fallback_embedding(self, text: str) -> list[float]:
        """
        Fallback deterministic embedding when API is unavailable.
        Uses a hash-based approach for consistency.
        """
        import hashlib
        import struct

        # Create a deterministic 384-dim vector from text
        hash_bytes = hashlib.sha256(text.encode()).digest()
        dim = 384

        # Use hash to seed pseudo-random values
        values = []
        for i in range(dim):
            seed_bytes = hashlib.sha256(hash_bytes + struct.pack("I", i)).digest()
            value = struct.unpack("f", seed_bytes[:4])[0]
            values.append(value)

        # Normalize to unit vector
        import math
        norm = math.sqrt(sum(v * v for v in values))
        if norm > 0:
            values = [v / norm for v in values]

        return values

    def _hash_text(self, text: str) -> str:
        """Create a short hash for cache key."""
        return hashlib.sha256(text.encode()).hexdigest()[:32]


def estimate_token_count(text: str) -> int:
    """Estimate token count for a text (rough approximation)."""
    # Rough: ~4 chars per token for English, ~2 for Vietnamese
    return len(text) // 3


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
) -> float:
    """Calculate estimated cost in USD."""
    pricing = TOKEN_PRICING.get(model, {"input": 1.0, "output": 2.0})
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)
