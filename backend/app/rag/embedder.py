"""Embedding service using local sentence-transformers with Redis caching."""

from __future__ import annotations

import asyncio
import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.redis_client import RedisClient

settings = get_settings()

# Module-level thread pool for CPU-bound sentence-transformers inference
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="st_embed")

# Singleton model instance (loaded once at first use)
_st_model: Any | None = None
_st_model_lock = asyncio.Lock()

# Singleton cross-encoder reranker
_cross_encoder_model: Any | None = None
_ce_model_lock = asyncio.Lock()


# ── Gemini embedding helpers ──────────────────────────────────────────────────

_gemini_clients: dict[str, Any] = {}  # singleton genai.Client per API key


def _get_gemini_client(api_key: str) -> Any:
    if api_key not in _gemini_clients:
        from google import genai
        _gemini_clients[api_key] = genai.Client(api_key=api_key)
    return _gemini_clients[api_key]


# gemini-embedding-001: stable, supports output_dimensionality 1–3072.
# Must match ST_EMBEDDING_DIM in config (1024 for bge-m3 / Pinecone index).
_GEMINI_EMBED_MODEL = "models/gemini-embedding-001"


def _gemini_embed_one_batch(api_key: str, texts: list[str]) -> list[list[float]]:
    """Embed a SINGLE sub-batch (≤100 texts) — exactly 1 API call."""
    from google.genai import types
    client = _get_gemini_client(api_key)
    config = types.EmbedContentConfig(output_dimensionality=settings.ST_EMBEDDING_DIM)
    resp = client.models.embed_content(
        model=_GEMINI_EMBED_MODEL,
        contents=texts,
        config=config,
    )
    return [list(emb.values) for emb in resp.embeddings]


async def _gemini_embed_batch(texts: list[str]) -> list[list[float]] | None:
    """Embed texts using Gemini with per-sub-batch key rotation.

    Each 100-text sub-batch uses a DIFFERENT key → each key gets only 1 request
    instead of 4, staying far under the 100 RPM limit per project.
    On 429, retries with the next key for that sub-batch (up to 3 attempts).
    Returns None if any sub-batch permanently fails → fallback to local ST.
    """
    import logging as _log
    _logger = _log.getLogger("document.embed")

    keys = settings.GEMINI_EMBED_KEYS
    if not keys:
        return None

    loop = asyncio.get_running_loop()
    # Gemini counts each text as 1 request → 100 texts/call = 100 requests = exactly hits 100 RPM.
    # Use 10 texts/call: 329 chunks → 33 sub-batches; each key gets ≤2 calls = 20 texts → safe.
    _SUB_BATCH = 10
    sub_batches = [texts[i:i + _SUB_BATCH] for i in range(0, len(texts), _SUB_BATCH)]
    all_embs: list[list[float]] = []
    key_idx = 0  # advances independently per successful sub-batch

    for batch_num, batch in enumerate(sub_batches):
        success = False
        for attempt in range(min(3, len(keys))):
            key = keys[(key_idx + attempt) % len(keys)]
            try:
                embs = await loop.run_in_executor(
                    _executor,
                    lambda k=key, b=batch: _gemini_embed_one_batch(k, b),
                )
                all_embs.extend(embs)
                key_idx = (key_idx + 1) % len(keys)
                success = True
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    _logger.warning(
                        "Gemini embed sub-batch %d: key %s… 429 (attempt %d/3)",
                        batch_num + 1, key[:8], attempt + 1,
                    )
                else:
                    _logger.warning(
                        "Gemini embed sub-batch %d: key %s… error: %s",
                        batch_num + 1, key[:8], e,
                    )

        if not success:
            _logger.warning(
                "Gemini embed sub-batch %d failed after 3 attempts — falling back to local ST",
                batch_num + 1,
            )
            return None

    return all_embs


def _load_model_sync() -> Any:
    """Load SentenceTransformer model synchronously (called in thread pool)."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.ST_EMBEDDING_MODEL)


def _load_cross_encoder_sync() -> Any:
    """Load CrossEncoder reranker synchronously (called in thread pool)."""
    from sentence_transformers import CrossEncoder
    return CrossEncoder(settings.RERANKER_MODEL)


class _FallbackModel:
    """Dummy model used when sentence-transformers is not available."""

    def __init__(self, embedding_dim: int = 768):
        self._dim = embedding_dim
        self._np = None  # lazily imported

    def _np_arr(self):
        if self._np is None:
            import numpy as np
            self._np = np
        return self._np

    def encode(self, texts, normalize_embeddings=True, **kwargs):
        np = self._np_arr()
        if isinstance(texts, str):
            vec = self._fallback_vec(texts)
            arr = np.array(vec, dtype=np.float32)
            if normalize_embeddings:
                norm = np.linalg.norm(arr)
                if norm > 0:
                    arr = arr / norm
            return arr
        return np.array(
            [self.encode(t, normalize_embeddings) for t in texts],
            dtype=np.float32,
        )

    def _fallback_vec(self, text: str) -> np.ndarray:
        import struct

        dim = self._dim
        hash_bytes = hashlib.sha256(text.encode()).digest()
        values = np.zeros(dim, dtype=np.float64)
        for i in range(dim):
            seed_bytes = hashlib.sha256(hash_bytes + struct.pack("I", i)).digest()
            values[i] = struct.unpack("f", seed_bytes[:4])[0]
        norm = np.linalg.norm(values)
        if norm > 0:
            values = values / norm
        return np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float32)


async def _get_model():
    """Get or lazily load the singleton SentenceTransformer model.

    Falls back to _FallbackModel (deterministic hash-based vectors) when
    sentence-transformers or transformers cannot be imported — so that the rest
    of the pipeline (parse, chunk, store in Pinecone) still runs.
    """
    global _st_model
    if _st_model is not None:
        return _st_model
    async with _st_model_lock:
        if _st_model is None:
            try:
                loop = asyncio.get_running_loop()
                _st_model = await loop.run_in_executor(_executor, _load_model_sync)
            except Exception as err:
                import logging
                logging.getLogger("document.embed").warning(
                    "sentence-transformers unavailable (%s) — using deterministic fallback embeddings",
                    err,
                )
                _st_model = _FallbackModel(embedding_dim=settings.ST_EMBEDDING_DIM)
    return _st_model


async def _get_cross_encoder():
    """Get or lazily load the singleton CrossEncoder reranker."""
    global _cross_encoder_model
    if _cross_encoder_model is not None:
        return _cross_encoder_model
    async with _ce_model_lock:
        if _cross_encoder_model is None:
            try:
                loop = asyncio.get_running_loop()
                _cross_encoder_model = await loop.run_in_executor(
                    _executor, _load_cross_encoder_sync
                )
            except Exception as err:
                import logging
                logging.getLogger("document.embed").warning(
                    "CrossEncoder reranker unavailable (%s) — reranking will be skipped",
                    err,
                )
                _cross_encoder_model = None
    return _cross_encoder_model


def close_embedding_client() -> None:
    """Shutdown the thread-pool executor (called on app shutdown)."""
    _executor.shutdown(wait=False)


class EmbeddingService:
    """Service for generating embeddings with Redis caching."""

    def __init__(self, redis: RedisClient | None = None):
        self.redis = redis
        self._embedding_dim = settings.ST_EMBEDDING_DIM  # 768 for mpnet-base

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
            return np.nan_to_num(cached, nan=0.0, posinf=1.0, neginf=-1.0)

        embedding = await self._call_embedding(text)
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
            new_embeddings = await self._call_embedding_batch(uncached_texts)
            for list_pos, (idx, emb) in enumerate(zip(uncached_indices, new_embeddings)):
                embeddings[idx] = emb
                cache_key = f"embed:text:{self._hash_text(uncached_texts[list_pos])}"
                await self._cache_set(cache_key, emb)

        return embeddings

    async def _call_embedding(self, text: str) -> list[float]:
        """Gemini primary, ST fallback (single text)."""
        result = await _gemini_embed_batch([text])
        if result:
            return result[0]
        model = await _get_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor,
            lambda: np.nan_to_num(
                np.asarray(model.encode(text, normalize_embeddings=True)),
                nan=0.0, posinf=1.0, neginf=-1.0,
            ).tolist(),
        )

    async def rerank(self, query: str, candidates: list[str], top_k: int = 8) -> list[tuple[int, float]]:
        """
        Rerank candidates using local CrossEncoder model.

        Args:
            query: The search query.
            candidates: List of candidate text strings.
            top_k: Number of top results to return.

        Returns:
            List of (candidate_index, relevance_score) sorted by score descending.
        """
        model = await _get_cross_encoder()
        if model is None:
            return []

        pairs = [[query, doc] for doc in candidates]

        def _predict():
            scores = model.predict(pairs)
            if hasattr(scores, "tolist"):
                scores = scores.tolist()
            return scores

        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(_executor, _predict)

        # Pair indices with scores and sort descending
        indexed = list(enumerate(scores))
        indexed.sort(key=lambda x: x[1], reverse=True)

        return indexed[:top_k]

    async def _call_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        """Gemini primary, ST fallback (batch)."""
        result = await _gemini_embed_batch(texts)
        if result is not None:
            return result
        model = await _get_model()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor,
            lambda: np.nan_to_num(
                np.asarray(model.encode(texts, normalize_embeddings=True, batch_size=32)),
                nan=0.0, posinf=1.0, neginf=-1.0,
            ).tolist(),
        )

    def _fallback_embedding(self, text: str) -> list[float]:
        """
        Fallback deterministic embedding when model is unavailable.
        Produces a zero-normalised vector matching ST_EMBEDDING_DIM (768).
        """
        import struct

        dim = self._embedding_dim
        hash_bytes = hashlib.sha256(text.encode()).digest()
        values = np.zeros(dim, dtype=np.float64)
        for i in range(dim):
            seed_bytes = hashlib.sha256(hash_bytes + struct.pack("I", i)).digest()
            values[i] = struct.unpack("f", seed_bytes[:4])[0]
        norm = np.linalg.norm(values)
        if norm > 0:
            values = values / norm
        vector = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float32)
        return vector.tolist()


async def embed_chunks(
    chunks: list[dict],
    doc_id: str,
    redis: RedisClient,
    progress_callback: Any | None = None,
) -> list[dict]:
    """
    Embed chunks with document-specific caching.

    Cache key: embed:{doc_id}:{chunk_id}  TTL 7 days.
    Check cache BEFORE encoding — only embed uncached chunks.

    Args:
        progress_callback: Optional async callable(completed: int, total: int)
            called after each sub-batch completes so callers can report progress.

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
            enriched["embedding"] = np.nan_to_num(cached, nan=0.0, posinf=1.0, neginf=-1.0)
            result_chunks.append(enriched)
        else:
            uncached_indices.append(i)
            uncached_chunks.append(chunk)
            result_chunks.append(None)  # Placeholder

    if uncached_chunks:
        texts = [c["content"] for c in uncached_chunks]
        total_texts = len(texts)

        # Primary: Gemini batch (100 texts/req, fast API)
        all_embeddings = await _gemini_embed_batch(texts)
        if all_embeddings is not None:
            if progress_callback:
                try:
                    await progress_callback(total_texts, total_texts)
                except Exception:
                    pass
        else:
            # Fallback: sentence-transformers (bypass service to avoid re-attempting Gemini)
            all_embeddings = []
            st_model = await _get_model()
            loop = asyncio.get_running_loop()
            batch_size = 32
            for batch_start in range(0, total_texts, batch_size):
                batch_texts = texts[batch_start:batch_start + batch_size]
                batch_embs = await loop.run_in_executor(
                    _executor,
                    lambda bt=batch_texts: np.nan_to_num(
                        np.asarray(st_model.encode(bt, normalize_embeddings=True, batch_size=32)),
                        nan=0.0, posinf=1.0, neginf=-1.0,
                    ).tolist(),
                )
                all_embeddings.extend(batch_embs)
                if progress_callback:
                    completed = min(batch_start + batch_size, total_texts)
                    try:
                        await progress_callback(completed, total_texts)
                    except Exception:
                        pass

        cache_tasks = []
        for idx, (chunk, embedding) in zip(uncached_indices, zip(uncached_chunks, all_embeddings)):
            chunk_id = chunk.get("chunk_id", f"chunk_{idx:04d}")
            cache_key = f"embed:{doc_id}:{chunk_id}"
            cache_tasks.append(service._cache_set(cache_key, embedding))

            enriched = dict(chunk)
            enriched["embedding"] = embedding
            result_chunks[idx] = enriched

        await asyncio.gather(*cache_tasks, return_exceptions=True)

    return [c for c in result_chunks if c is not None]


def estimate_token_count(text: str) -> int:
    """Estimate token count for a text (rough approximation)."""
    return len(text) // 3


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int = 0,
) -> float:
    """
    Stub kept for API compatibility.
    Local sentence-transformers has no token cost — always returns 0.0.
    """
    return 0.0
