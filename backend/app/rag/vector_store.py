"""Pinecone vector store operations — single namespace per document."""

import logging
import unicodedata
from app.rag.structure import normalize_chapter_id
from app.core.config import get_settings

logger = logging.getLogger("app.rag.vector_store")
settings = get_settings()


def _make_ascii_namespace(namespace: str) -> str:
    """
    Convert namespace to ASCII-safe string for Pinecone.
    - Normalize Unicode (NFC), strip diacritics
    - Replace non-ASCII letters with ASCII equivalents
    - Replace non-printable / special chars with underscore
    """
    ascii_str = unicodedata.normalize("NFD", namespace)
    ascii_str = "".join(c for c in ascii_str if unicodedata.category(c) != "Mn")
    ascii_str = "".join(c if ord(c) < 128 else "_" for c in ascii_str)
    import re
    ascii_str = re.sub(r"_+", "_", ascii_str).strip("_")
    if not ascii_str:
        import hashlib
        ascii_str = hashlib.md5(namespace.encode()).hexdigest()
    return ascii_str


def _doc_namespace(document_id: str) -> str:
    """Build single namespace for a document: doc_{uuid_no_dashes}."""
    clean_id = document_id.replace("-", "")
    return _make_ascii_namespace(f"doc_{clean_id}")


class VectorStore:
    """Pinecone vector store manager — single namespace per document."""

    def __init__(self):
        self._client = None
        self._index = None

    async def _get_index(self):
        """Lazy-load Pinecone index. Raises RuntimeError on connection failure."""
        if self._index is None:
            try:
                from pinecone import Pinecone, ServerlessSpec
                pc = Pinecone(api_key=settings.PINECONE_API_KEY)

                existing = pc.list_indexes().names()

                if settings.PINECONE_INDEX not in existing:
                    pc.create_index(
                        name=settings.PINECONE_INDEX,
                        dimension=settings.ST_EMBEDDING_DIM,
                        metric="cosine",
                        spec=ServerlessSpec(
                            cloud=settings.PINECONE_CLOUD,
                            region=settings.PINECONE_REGION,
                        ),
                    )

                self._index = pc.Index(settings.PINECONE_INDEX)
                logger.info("Pinecone index '%s' connected successfully", settings.PINECONE_INDEX)

            except ImportError as e:
                raise RuntimeError(
                    "Pinecone package not installed or conflict detected. "
                    "Run: pip uninstall pinecone-client -y && pip install pinecone"
                ) from e
            except Exception as e:
                raise RuntimeError(f"Pinecone connection failed: {e}") from e

        return self._index

    async def upsert_chunks(
        self,
        document_id: str,
        chapter_id: str,
        chunks: list[dict],
    ) -> None:
        """
        Upsert chunks to Pinecone — single namespace per document.

        Namespace: doc_{document_id} (all chapters in same namespace).
        chapter_id is stored in metadata for filtering.
        Each chunk dict must have: chunk_id, content, chapter, chapter_id,
        section, section_id, content_type, latex_repr, page_number.
        Chunks must already have an "embedding" field.
        """
        index = await self._get_index()  # raises RuntimeError if unavailable

        namespace = _doc_namespace(document_id)
        records = []

        import numpy as np
        for chunk in chunks:
            embedding = chunk.get("embedding")
            if embedding is None:
                continue
            if isinstance(embedding, np.ndarray) and embedding.size == 0:
                continue
            embedding = np.nan_to_num(embedding, nan=0.0, posinf=1.0, neginf=-1.0).tolist()

            chunk_id = chunk.get("chunk_id", "")
            safe_chunk_id = "".join(c if ord(c) < 128 else "_" for c in chunk_id)
            if not safe_chunk_id:
                safe_chunk_id = "chunk_unknown"

            records.append({
                "id": safe_chunk_id,
                "values": embedding,
                "metadata": {
                    "document_id": document_id,
                    "chunk_id": chunk.get("chunk_id", ""),
                    "chapter": chunk.get("chapter", ""),
                    "chapter_id": chapter_id,  # Explicit chapter_id for metadata filtering
                    "section": chunk.get("section", ""),
                    "section_id": chunk.get("section_id", ""),
                    "content_type": chunk.get("content_type", "text"),
                    "content": chunk.get("content", "")[:2000],
                    "latex_repr": chunk.get("latex_repr", "") or "",
                    "page_number": chunk.get("page_number") or 0,
                },
            })

        if not records:
            return

        def _upsert_batch(batch_records, ns):
            for attempt in range(3):
                try:
                    index.upsert(vectors=batch_records, namespace=ns)
                    return
                except Exception as e:
                    if attempt < 2:
                        logger.warning(
                            "Pinecone upsert attempt %d failed for namespace '%s': %s — retrying",
                            attempt + 1, ns, e,
                        )
                    else:
                        logger.error(
                            "Pinecone upsert FAILED for namespace '%s' after 3 attempts: %s",
                            ns, e,
                        )
                        raise

        import asyncio
        loop = asyncio.get_running_loop()
        for i in range(0, len(records), 100):
            batch = records[i:i + 100]
            await loop.run_in_executor(None, _upsert_batch, batch, namespace)

    async def count_chunks_in_scope(
        self,
        doc_id: str,
        scope_chapters: list[str],
    ) -> int:
        """
        Count total chunks in the document namespace.

        With single namespace, this just returns the total vector count
        for the document. Per-chapter count isn't available without querying.
        """
        index = await self._get_index()
        if not index:
            logger.warning("Pinecone index unavailable for count_chunks_in_scope")
            return 0

        try:
            stats = index.describe_index_stats()
            if not stats:
                return 0
            namespaces: dict = stats.get("namespaces", {})
            ns_key = _doc_namespace(doc_id)
            return namespaces.get(ns_key, {}).get("vector_count", 0)
        except Exception:
            return 0

    async def query_namespace(
        self,
        doc_id: str,
        chapter_id: str,
        query_embedding: list[float],
        top_k: int = 20,
        content_types: list[str] | None = None,
        filter_metadata: dict | None = None,
    ) -> list[dict]:
        """
        Query chunks from a document namespace, filtered by chapter_id.

        Namespace: doc_{document_id} (single namespace per document).
        Uses Pinecone metadata filter: {"chapter_id": chapter_id}
        Returns top_k results sorted by score (descending).

        Args:
            filter_metadata: Optional Pinecone metadata filter dict.
                             e.g. {"chapter_id": {"$eq": "ch6"}} to force-fetch
                             chunks from a specific chapter.
        """
        try:
            index = await self._get_index()
        except RuntimeError as e:
            logger.warning(
                "Pinecone unavailable for query_namespace (doc=%s ch=%s): %s",
                doc_id, chapter_id, e,
            )
            return []

        namespace = _doc_namespace(doc_id)

        import numpy as np
        query_embedding = np.nan_to_num(query_embedding, nan=0.0, posinf=1.0, neginf=-1.0).tolist()

        # No metadata filter — query ALL vectors in the document namespace.
        # With single namespace (~300-600 vectors), this is fast.
        # Chapter relevance is handled by query embedding + reranking.
        try:
            query_kwargs: dict = dict(
                vector=query_embedding,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
            )
            if filter_metadata:
                query_kwargs["filter"] = filter_metadata
            result = index.query(**query_kwargs)

            all_results = []
            for match in result.get("matches", []):
                all_results.append({
                    "chunk_id": match["id"],
                    "score": match["score"],
                    "metadata": match.get("metadata", {}),
                })

            # ── Legacy fallback: try old per-chapter namespace if new returns 0 ──
            if not all_results and chapter_id:
                legacy_ns = _make_ascii_namespace(f"{doc_id}_{chapter_id}")
                if legacy_ns != namespace:
                    logger.info(
                        "[query_namespace] 0 results in new ns '%s', trying legacy ns '%s'",
                        namespace, legacy_ns,
                    )
                    legacy_result = index.query(
                        vector=query_embedding,
                        top_k=top_k,
                        namespace=legacy_ns,
                        include_metadata=True,
                    )
                    for match in legacy_result.get("matches", []):
                        all_results.append({
                            "chunk_id": match["id"],
                            "score": match["score"],
                            "metadata": match.get("metadata", {}),
                        })

            all_results.sort(key=lambda x: x["score"], reverse=True)

            logger.info(
                "[query_namespace] doc=%s, chapter=%s, namespace='%s', "
                "top_k=%d, results=%d",
                doc_id, chapter_id, namespace, top_k, len(all_results),
            )

            return all_results

        except Exception as e:
            logger.warning(
                "[query_namespace] FAILED doc=%s, chapter=%s, namespace='%s': %s",
                doc_id, chapter_id, namespace, e,
            )
            return []

    async def query_textbook_namespace(
        self,
        namespace: str,
        query_embedding: list[float],
        top_k: int = 40,
        filter_metadata: dict | None = None,
    ) -> list[dict]:
        """
        Query a raw textbook namespace (admin-uploaded) directly.
        No doc_id required — namespace is provided as-is (already ASCII-safe).
        """
        try:
            index = await self._get_index()
        except RuntimeError as e:
            logger.warning("[query_textbook_namespace] Pinecone unavailable: %s", e)
            return []

        import numpy as np
        query_embedding = np.nan_to_num(query_embedding, nan=0.0, posinf=1.0, neginf=-1.0).tolist()

        try:
            query_kwargs: dict = dict(
                vector=query_embedding,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
            )
            if filter_metadata:
                query_kwargs["filter"] = filter_metadata
            result = index.query(**query_kwargs)

            results = [
                {
                    "chunk_id": m["id"],
                    "score": m["score"],
                    "metadata": m.get("metadata", {}),
                }
                for m in result.get("matches", [])
            ]
            logger.info(
                "[query_textbook_namespace] namespace='%s', top_k=%d, results=%d",
                namespace, top_k, len(results),
            )
            return results
        except Exception as e:
            logger.warning("[query_textbook_namespace] FAILED namespace='%s': %s", namespace, e)
            return []

    async def delete_document_vectors(
        self,
        doc_id: str,
        chapters: list[str],
    ) -> None:
        """
        Delete all vectors for a document.

        With single namespace, simply delete the entire doc namespace.
        The chapters parameter is kept for API compatibility but ignored.
        """
        index = await self._get_index()
        if not index:
            logger.warning(
                "Pinecone index unavailable — cannot delete vectors for doc %s", doc_id
            )
            return

        namespace = _doc_namespace(doc_id)
        for attempt in range(3):
            try:
                index.delete(delete_all=True, namespace=namespace)
                logger.info("Deleted Pinecone namespace '%s' for doc %s", namespace, doc_id)
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning(
                        "Pinecone delete attempt %d failed for namespace '%s': %s — retrying",
                        attempt + 1, namespace, e,
                    )
                else:
                    logger.error(
                        "Pinecone delete FAILED for namespace '%s' after 3 attempts: %s",
                        namespace, e,
                    )

        # Also try to clean up legacy per-chapter namespaces (migration)
        try:
            stats = index.describe_index_stats()
            namespaces = stats.get("namespaces", {}) if stats else {}
            doc_prefix = doc_id.replace("-", "")
            for ns in list(namespaces.keys()):
                if ns.startswith(doc_prefix) and ns != namespace:
                    try:
                        index.delete(delete_all=True, namespace=ns)
                        logger.info("Deleted legacy namespace '%s' for doc %s", ns, doc_id)
                    except Exception:
                        pass
        except Exception:
            pass

    async def delete_all_document_vectors(self, doc_id: str) -> bool:
        """
        Delete all vectors for a document (all namespaces including legacy).

        Lists all namespaces matching this doc_id prefix and deletes each.
        Returns True if Pinecone is reachable, False if unreachable.
        """
        index = await self._get_index()
        if not index:
            logger.warning(
                "Pinecone index unavailable — cannot delete vectors for doc %s", doc_id
            )
            return False

        try:
            stats = index.describe_index_stats()
            namespaces: dict = stats.get("namespaces", {})
            deleted_any = False
            doc_prefix = doc_id.replace("-", "")
            for ns in namespaces:
                if ns.startswith(doc_prefix) or ns.startswith(f"doc_{doc_prefix}") or ns.startswith(f"{doc_id}_"):
                    try:
                        index.delete(delete_all=True, namespace=ns)
                        logger.info("Deleted Pinecone namespace '%s' (doc %s)", ns, doc_id)
                        deleted_any = True
                    except Exception as e:
                        logger.error("Failed to delete namespace '%s': %s", ns, e)
            return deleted_any or True
        except Exception as e:
            logger.error(
                "describe_index_stats failed during delete_all for doc %s: %s",
                doc_id, e,
            )
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


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get the singleton VectorStore instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
