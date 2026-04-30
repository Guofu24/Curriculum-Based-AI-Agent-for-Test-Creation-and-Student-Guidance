"""Pinecone vector store operations."""

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


class VectorStore:
    """Pinecone vector store manager."""

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
        Upsert chunks to Pinecone with namespace per chapter.

        Namespace: {doc_id}_{chapter_id} (e.g., "doc123_ch1")
        Each chunk dict must have: chunk_id, content, chapter, chapter_id,
        section, section_id, content_type, latex_repr, page_number.
        Chunks must already have an "embedding" field.
        """
        index = await self._get_index()  # raises RuntimeError if unavailable

        namespace = _make_ascii_namespace(f"{document_id}_{chapter_id}")
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
                    "chapter_id": chunk.get("chapter_id", ""),
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

        for i in range(0, len(records), 100):
            batch = records[i:i + 100]
            _upsert_batch(batch, namespace)

    async def count_chunks_in_scope(
        self,
        doc_id: str,
        scope_chapters: list[str],
    ) -> int:
        """
        Count total chunks across all scope chapters.

        Uses describe_index_stats() for efficiency (single API call),
        then filters by prefix-match on namespace. Falls back to 0
        if the index or stats are unavailable.
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
            total = 0
            for chapter in scope_chapters:
                chapter_id = normalize_chapter_id(chapter)
                ns_key = _make_ascii_namespace(f"{doc_id}_{chapter_id}")
                total += namespaces.get(ns_key, {}).get("vector_count", 0)
            return total
        except Exception:
            return 0

    async def query_namespace(
        self,
        doc_id: str,
        chapter_id: str,
        query_embedding: list[float],
        top_k: int = 20,
        content_types: list[str] | None = None,
    ) -> list[dict]:
        """
        Query chunks from a specific chapter namespace.

        Namespace: {doc_id}_{chapter_id}
        Returns top_k results sorted by score (descending).

        Args:
            content_types: If provided, only return chunks matching these content types.
                          Examples: ["definition"], ["example", "exercise"], ["formula"]
        """
        try:
            index = await self._get_index()
        except RuntimeError as e:
            logger.warning(
                "Pinecone unavailable for query_namespace (doc=%s ch=%s): %s",
                doc_id, chapter_id, e,
            )
            return []

        namespace = _make_ascii_namespace(f"{doc_id}_{chapter_id}")

        import numpy as np
        query_embedding = np.nan_to_num(query_embedding, nan=0.0, posinf=1.0, neginf=-1.0).tolist()

        try:
            result = index.query(
                vector=query_embedding,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
            )

            all_results = []
            for match in result.get("matches", []):
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

            # NOTE: content_type filter removed — chunks are stored with
            # default content_type='text', so Bloom-based content_type
            # filtering (e.g., 'definition', 'theorem') would discard
            # ALL results. Bloom targeting is handled at outline/builder level.

            return all_results

        except Exception as e:
            logger.warning(
                "[query_namespace] FAILED doc=%s, chapter=%s, namespace='%s': %s",
                doc_id, chapter_id, namespace, e,
            )
            return []

    async def delete_document_vectors(
        self,
        doc_id: str,
        chapters: list[str],
    ) -> None:
        """
        Delete all vectors for specific chapters of a document.

        Deletes namespace {doc_id}_{chapter_id} for each chapter in the list,
        plus the 'ch_unknown' namespace (chunks without detected headings).
        Uses retry loop to handle transient Pinecone errors.
        """
        index = await self._get_index()
        if not index:
            logger.warning(
                "Pinecone index unavailable — cannot delete vectors for doc %s", doc_id
            )
            return

        all_chapters = list(chapters) + ["ch_unknown"]

        for chapter_id in all_chapters:
            namespace = _make_ascii_namespace(f"{doc_id}_{chapter_id}")
            for attempt in range(3):
                try:
                    index.delete(delete_all=True, namespace=namespace)
                    logger.info(
                        "Deleted Pinecone namespace '%s' for doc %s", namespace, doc_id
                    )
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

    async def delete_all_document_vectors(self, doc_id: str) -> bool:
        """
        Delete all vectors for a document (all namespaces).

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
            for ns in namespaces:
                if ns.startswith(doc_id.replace('-', '')) or ns.startswith(f"{doc_id}_"):
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
