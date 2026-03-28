"""Pinecone vector store operations."""

from typing import Any
import uuid

from app.core.config import get_settings
from app.rag.chunker import Chunk

settings = get_settings()


class VectorStore:
    """Pinecone vector store manager."""

    def __init__(self):
        self._client = None
        self._index = None

    async def _get_index(self):
        """Lazy-load Pinecone index."""
        if self._index is None:
            try:
                from pinecone import Pinecone
                pc = Pinecone(api_key=settings.PINECONE_API_KEY)

                # Check if index exists, create if not
                existing = [idx.name for idx in pc.list_indexes()]

                if settings.PINECONE_INDEX not in existing:
                    pc.create_index(
                        name=settings.PINECONE_INDEX,
                        dimension=settings.OPENAI_EMBEDDING_DIM,
                        metric="cosine",
                        cloud=settings.PINECONE_CLOUD,
                        region=settings.PINECONE_REGION,
                    )

                self._index = pc.Index(settings.PINECONE_INDEX)

            except ImportError:
                self._index = None  # Pinecone not available
            except Exception:
                self._index = None

        return self._index

    async def upsert_chunks(
        self,
        document_id: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> bool:
        """Upsert chunks to Pinecone with namespace per chapter."""
        index = await self._get_index()
        if not index:
            return False

        # Group chunks by chapter
        chapter_groups: dict[str, list[dict]] = {}

        for chunk, embedding in zip(chunks, embeddings):
            namespace = f"{document_id}_{chunk.chapter_id}"

            if namespace not in chapter_groups:
                chapter_groups[namespace] = []

            record = {
                "id": chunk.chunk_id,
                "values": embedding,
                "metadata": {
                    "document_id": document_id,
                    "chunk_id": chunk.chunk_id,
                    "chapter": chunk.chapter,
                    "chapter_id": chunk.chapter_id,
                    "section": chunk.section,
                    "section_id": chunk.section_id,
                    "content_type": chunk.content_type,
                    "content": chunk.content[:2000],  # Truncate for storage
                    "latex_repr": chunk.latex_repr or "",
                    "page_number": chunk.page_number or 0,
                },
            }
            chapter_groups[namespace].append(record)

        # Upsert each namespace
        for namespace, records in chapter_groups.items():
            try:
                # Upsert in batches of 100
                for i in range(0, len(records), 100):
                    batch = records[i:i + 100]
                    index.upsert(vectors=batch, namespace=namespace)
            except Exception:
                continue

        return True

    async def query(
        self,
        document_id: str,
        chapter_ids: list[str],
        query_embedding: list[float],
        top_k: int = 20,
        filter_dict: dict | None = None,
    ) -> list[dict]:
        """Query chunks from specific chapters in document."""
        index = await self._get_index()
        if not index:
            return []

        all_results = []

        for chapter_id in chapter_ids:
            namespace = f"{document_id}_{chapter_id}"
            try:
                result = index.query(
                    vector=query_embedding,
                    top_k=top_k,
                    namespace=namespace,
                    include_metadata=True,
                    filter=filter_dict,
                )

                for match in result.get("matches", []):
                    all_results.append({
                        "chunk_id": match["id"],
                        "score": match["score"],
                        "metadata": match.get("metadata", {}),
                    })

            except Exception:
                continue

        # Sort by score and deduplicate
        all_results.sort(key=lambda x: x["score"], reverse=True)

        return all_results[:top_k]

    async def delete_document_vectors(self, document_id: str) -> bool:
        """Delete all vectors for a document."""
        index = await self._get_index()
        if not index:
            return False

        try:
            # Delete by metadata filter
            index.delete(
                filter={"document_id": {"$eq": document_id}},
                delete_all=False,
            )
            return True
        except Exception:
            return False

    async def describe_index_stats(self) -> dict | None:
        """Get index statistics."""
        index = await self._get_index()
        if not index:
            return None

        try:
            return index.describe_index_stats()
        except Exception:
            return None


# Singleton instance
_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get the singleton VectorStore instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
