"""Embedding service with Redis caching."""

from typing import Any
import hashlib

from openai import RateLimitError, APIError, APITimeoutError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.core.config import get_settings
from app.core.redis_client import RedisClient

settings = get_settings()

# Token pricing (approximate, per 1M tokens)
TOKEN_PRICING = {
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}

_embedding_client: "AsyncOpenAI | None" = None


def _get_openai_client() -> "AsyncOpenAI":
    """Get or create singleton OpenAI client for embeddings."""
    global _embedding_client
    if _embedding_client is None:
        from openai import AsyncOpenAI
        _embedding_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
    return _embedding_client


def close_embedding_client() -> None:
    """Close the singleton OpenAI client."""
    global _embedding_client
    if _embedding_client is not None:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_embedding_client.close())
        except RuntimeError:
            asyncio.run(_embedding_client.aclose())
        _embedding_client = None


class EmbeddingService:
    """Service for generating embeddings with Redis caching."""

    def __init__(self, redis: RedisClient | None = None):
        self.redis = redis
        self._embedding_dim = settings.OPENAI_EMBEDDING_DIM  # 3072 for text-embedding-3-large

    def _hash_text(self, text: str) -> str:
        """Create a short hash for cache key."""
        return hashlib.sha256(text.encode()).hexdigest()[:32]

    async def _cache_get(self, cache_key: str) -> list[float] | None:
        """Get cached embedding from Redis, returning None on any failure."""
        if not self.redis:
            return None
        try:
            cached = await self.redis.get_json(cache_key)
            return cached["embedding"] if cached else None
        except Exception:
            return None

    async def _cache_set(self, cache_key: str, embedding: list[float]) -> None:
        """Store embedding in Redis cache, silently ignoring failures."""
        if not self.redis:
            return
        try:
            await self.redis.set_json(
                cache_key,
                {"embedding": embedding},
                ttl=settings.EMBEDDING_CACHE_TTL_SECONDS,
            )
        except Exception:
            pass

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text with Redis caching."""
        cache_key = f"embed:text:{self._hash_text(text)}"
        cached = await self._cache_get(cache_key)
        if cached:
            return cached

        embedding = await self._call_embedding_api(text)
        await self._cache_set(cache_key, embedding)
        return embedding

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts, checking cache per item."""
        embeddings: list[list[float]] = []
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            cache_key = f"embed:text:{self._hash_text(text)}"
            cached = await self._cache_get(cache_key)
            if cached:
                embeddings.append(cached)
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)
                embeddings.append([])  # Placeholder

        if uncached_texts:
            new_embeddings = await self._call_embedding_api_batch(uncached_texts)
            for idx, emb in zip(uncached_indices, new_embeddings):
                embeddings[idx] = emb
                cache_key = f"embed:text:{self._hash_text(uncached_texts[uncached_indices.index(idx)])}"
                await self._cache_set(cache_key, emb)

        return embeddings

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError)),
        reraise=True,
    )
    async def _call_embedding_api(self, text: str) -> list[float]:
        """Call OpenAI embedding API with 3x retry on rate-limit/timeout."""
        client = _get_openai_client()
        response = await client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError)),
        reraise=True,
    )
    async def _call_embedding_api_batch(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI embedding API in batch with 3x retry."""
        client = _get_openai_client()
        response = await client.embeddings.create(
            model=settings.OPENAI_EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def _fallback_embedding(self, text: str) -> list[float]:
        """
        Fallback deterministic embedding when API is unavailable.
        Produces a vector with the correct dimensionality (3072) for
        text-embedding-3-large compatibility.
        """
        import struct
        import math

        dim = self._embedding_dim
        hash_bytes = hashlib.sha256(text.encode()).digest()

        values = []
        for i in range(dim):
            seed_bytes = hashlib.sha256(hash_bytes + struct.pack("I", i)).digest()
            value = struct.unpack("f", seed_bytes[:4])[0]
            values.append(value)

        norm = math.sqrt(sum(v * v for v in values))
        if norm > 0:
            values = [v / norm for v in values]

        return values


async def embed_chunks(
    chunks: list[dict],
    doc_id: str,
    redis: RedisClient,
) -> list[dict]:
    """
    Embed chunks with document-specific caching (G16).

    Cache key: embed:{doc_id}:{chunk_id} TTL 7 days.
    Check cache BEFORE calling OpenAI — only embed uncached chunks.

    Returns list of chunks enriched with `embedding` field.

    Each chunk dict should have: chunk_id, content (text to embed).
    """
    service = EmbeddingService(redis)
    result_chunks: list[dict] = []
    uncached_indices: list[int] = []
    uncached_chunks: list[dict] = []

    for i, chunk in enumerate(chunks):
        chunk_id = chunk.get("chunk_id", f"chunk_{i:04d}")
        cache_key = f"embed:{doc_id}:{chunk_id}"
        cached = await service._cache_get(cache_key)

        if cached:
            enriched = dict(chunk)
            enriched["embedding"] = cached
            result_chunks.append(enriched)
        else:
            uncached_indices.append(i)
            uncached_chunks.append(chunk)
            result_chunks.append(None)  # Placeholder

    if uncached_chunks:
        texts = [c["content"] for c in uncached_chunks]
        new_embeddings = await service.embed_texts(texts)

        for idx, (chunk, embedding) in zip(uncached_indices, new_embeddings):
            chunk_id = chunk.get("chunk_id", f"chunk_{idx:04d}")
            cache_key = f"embed:{doc_id}:{chunk_id}"
            await service._cache_set(cache_key, embedding)

            enriched = dict(chunk)
            enriched["embedding"] = embedding
            result_chunks[idx] = enriched

    return [c for c in result_chunks if c is not None]


def estimate_token_count(text: str) -> int:
    """Estimate token count for a text (rough approximation)."""
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
