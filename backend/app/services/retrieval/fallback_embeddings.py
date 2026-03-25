from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings


class DeterministicHashEmbeddings(Embeddings):
    """A lightweight fallback embedding backend for local/dev resilience.

    This is not a semantic replacement for sentence-transformers. It exists so
    the document pipeline can keep working when the local Python environment has
    an incompatible `sentence-transformers` / `transformers` / `torchvision`
    stack. Vectors are deterministic, normalized, and dimension-stable so they
    remain compatible with the configured Pinecone index.
    """

    def __init__(self, dimension: int = 384, salt: str = "examai-hash-v1") -> None:
        self.dimension = max(int(dimension or 384), 8)
        self.salt = salt

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_text(text) for text in texts]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed_text(text)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    def _embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = self._tokenize(text)
        if not tokens:
            return vector

        for index, token in enumerate(tokens):
            digest = hashlib.blake2b(
                f"{self.salt}:{token}:{index % 4}".encode("utf-8"),
                digest_size=16,
            ).digest()
            for offset in range(0, len(digest), 4):
                chunk = digest[offset:offset + 4]
                bucket = int.from_bytes(chunk[:2], "little") % self.dimension
                sign = 1.0 if chunk[2] % 2 == 0 else -1.0
                weight = 1.0 + (chunk[3] / 255.0) * 0.25
                vector[bucket] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0:
            return vector
        return [value / norm for value in vector]

    def _tokenize(self, text: str) -> list[str]:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return []

        tokens = re.findall(r"\w+", normalized)
        if len(tokens) <= 1:
            return tokens

        bigrams = [
            f"{tokens[position]}_{tokens[position + 1]}"
            for position in range(len(tokens) - 1)
        ]
        return tokens + bigrams


class NoOpVectorStore:
    """A no-network vector store used when the runtime is in degraded fallback mode."""

    def __init__(self, namespace: str | None = None) -> None:
        self.namespace = namespace

    async def aadd_texts(self, **kwargs):
        _ = kwargs
        return []

    async def asimilarity_search_with_score(self, **kwargs):
        _ = kwargs
        return []
