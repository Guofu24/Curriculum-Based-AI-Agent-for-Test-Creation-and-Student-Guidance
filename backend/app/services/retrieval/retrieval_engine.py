"""
Retrieval engine for the active MVP runtime

Responsibilities:
- Hybrid search (vector similarity + BM25 keyword match)
- Strict chapter/document filtering
- Re-rank results for relevance
- Return contextual chunks for each question slot
"""

import asyncio
import json
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from rank_bm25 import BM25Okapi

from app.core.runtime_models import ExamBlueprint, QuestionSlot, RetrievedContext
from app.core.config import settings
from app.models.textbook import TextbookChunk

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """
    Retrieves relevant document content for question generation.
    Uses hybrid search: Pinecone vector similarity + PostgreSQL BM25 keyword scoring.
    """

    TOP_K_VECTOR = 10
    TOP_K_BM25 = 10
    FINAL_TOP_K = 5
    MAX_VECTOR_EXPANSION = 3

    def __init__(self, vector_store, db_session: AsyncSession = None):
        self.vector_store = vector_store
        self.db_session = db_session
        self._bm25_cache: dict[tuple[str, tuple[int, ...]], dict] = {}

    async def retrieve_for_blueprint(
        self,
        blueprint: ExamBlueprint,
        document_id: str,
        chapters: list[int],
        constraints: dict,
    ) -> list[RetrievedContext]:
        """Retrieve relevant context for each question slot in the blueprint."""
        max_concurrency = self._resolve_max_concurrency(constraints)
        semaphore = asyncio.Semaphore(max_concurrency)

        async def retrieve_slot(slot: QuestionSlot) -> RetrievedContext:
            async with semaphore:
                return await self._retrieve_for_slot(
                    slot=slot,
                    document_id=document_id,
                    chapters=chapters,
                    constraints=constraints,
                )

        return await asyncio.gather(*(retrieve_slot(slot) for slot in blueprint.slots))

    async def _retrieve_for_slot(
        self,
        slot: QuestionSlot,
        document_id: str,
        chapters: list[int],
        constraints: dict,
    ) -> RetrievedContext:
        """Retrieve context for a single question slot using hybrid search."""
        query = self._build_query(slot)
        chapter_scope = self._resolve_chapter_scope(
            requested_chapters=chapters,
            target_chapter=slot.target_chapter,
        )

        vector_results = await self._vector_search(
            query=query,
            chapters=chapter_scope,
        )

        bm25_results = await self._bm25_search(
            query=query,
            document_id=document_id,
            chapters=chapter_scope,
        )

        merged = self._hybrid_merge(vector_results, bm25_results)
        top_results = merged[:self.FINAL_TOP_K]

        return RetrievedContext(
            slot_number=slot.slot_number,
            query=query,
            scope_tags=list(getattr(slot, "scope_tags", []) or []),
            chunks=[
                {
                    "id": r.get("id", ""),
                    "text": r.get("text", ""),
                    "metadata": r.get("metadata", {}),
                    "score": r.get("score", 0.0),
                }
                for r in top_results
            ],
            combined_text="\n\n---\n\n".join(r.get("text", "") for r in top_results),
        )

    def _build_query(self, slot: QuestionSlot) -> str:
        """Build a search query from the question slot specifications."""
        preferred_query = getattr(slot, "preferred_query", "")
        if preferred_query:
            return preferred_query
        parts = []
        if slot.target_topics:
            parts.append(" ".join(slot.target_topics))
        if slot.target_chapter and slot.target_chapter > 0:
            parts.append(f"chapter {slot.target_chapter}")
        parts.append(f"{slot.bloom_level} level {slot.question_type} question")
        return " ".join(parts)

    async def _vector_search(
        self,
        query: str,
        chapters: list[int],
    ) -> list:
        """Run vector search and apply strict chapter filtering when requested."""
        fetch_k = self.TOP_K_VECTOR
        if chapters:
            fetch_k = max(self.TOP_K_VECTOR, self.TOP_K_VECTOR * self.MAX_VECTOR_EXPANSION)

        vector_results = await self._safe_vector_search(
            query=query,
            k=fetch_k,
        )

        if not chapters:
            return vector_results

        filtered = []
        for item in vector_results:
            if not (hasattr(item, "__len__") and len(item) == 2):
                continue
            doc, _ = item
            metadata = doc.metadata if isinstance(doc.metadata, dict) else {}
            if self._matches_chapters(metadata, chapters):
                filtered.append(item)
            if len(filtered) >= self.TOP_K_VECTOR:
                break

        return filtered

    async def _bm25_search(
        self,
        query: str,
        document_id: str,
        chapters: list[int],
    ) -> list[dict]:
        """BM25 keyword search over chunk text stored in PostgreSQL."""
        if self.db_session is None:
            return []

        scope_key = tuple(sorted(set(int(ch) for ch in chapters if isinstance(ch, int) and ch > 0)))
        cache_key = (document_id, scope_key)
        payload = self._bm25_cache.get(cache_key)

        if payload is None:
            payload = await self._build_bm25_payload(
                document_id=document_id,
                chapters=list(scope_key),
            )
            self._bm25_cache[cache_key] = payload

        bm25 = payload.get("bm25")
        if bm25 is None:
            return []

        tokenized_query = self._tokenize(query)
        scores = bm25.get_scores(tokenized_query)

        rows = payload["rows"]
        results = []
        for i, score in enumerate(scores):
            row = rows[i]
            results.append(
                {
                    "id": row["id"],
                    "text": row["text"],
                    "metadata": row["metadata"],
                    "score": float(score),
                }
            )

        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:self.TOP_K_BM25]

    async def _build_bm25_payload(
        self,
        document_id: str,
        chapters: list[int],
    ) -> dict:
        """Build and cache BM25 corpus by document + chapter scope."""
        result = await self.db_session.execute(
            select(TextbookChunk).where(TextbookChunk.textbook_id == document_id)
        )
        db_rows = list(result.scalars().all())
        if not db_rows:
            return {"bm25": None, "rows": []}

        rows: list[dict] = []
        for row in db_rows:
            metadata: dict = {}
            try:
                if row.metadata_json:
                    metadata = json.loads(row.metadata_json)
            except (json.JSONDecodeError, TypeError):
                metadata = {}

            metadata = dict(metadata or {})
            metadata.setdefault("chapter", row.chapter or "")
            metadata.setdefault("parent_heading", row.parent_heading or "")
            metadata.setdefault("page", row.page)
            metadata.setdefault("chunk_id", row.chunk_id)
            metadata["chapter_number"] = self._extract_chapter_number_from_metadata(metadata)

            if chapters and not self._matches_chapters(metadata, chapters):
                continue

            rows.append(
                {
                    "id": row.chunk_id,
                    "text": row.content,
                    "metadata": metadata,
                }
            )

        if not rows:
            return {"bm25": None, "rows": []}

        tokenized_corpus = [self._tokenize(r["text"]) for r in rows]
        return {
            "bm25": BM25Okapi(tokenized_corpus),
            "rows": rows,
        }

    def _hybrid_merge(
        self,
        vector_results: list,
        bm25_results: list[dict],
        vector_weight: float = 0.6,
        bm25_weight: float = 0.4,
    ) -> list[dict]:
        """
        Reciprocal Rank Fusion (RRF) to merge vector and BM25 results.
        """
        k = 60

        scores = {}

        for rank, item in enumerate(vector_results):
            if hasattr(item, "__len__") and len(item) == 2:
                doc, _score = item
                doc_id = doc.metadata.get("chunk_id", str(rank))
                rrf_score = vector_weight / (k + rank + 1)
                if doc_id not in scores:
                    scores[doc_id] = {
                        "id": doc_id,
                        "text": doc.page_content,
                        "metadata": doc.metadata,
                        "score": 0.0,
                    }
                scores[doc_id]["score"] += rrf_score

        for rank, item in enumerate(bm25_results):
            doc_id = item.get("id", str(rank))
            rrf_score = bm25_weight / (k + rank + 1)
            if doc_id not in scores:
                scores[doc_id] = {
                    "id": doc_id,
                    "text": item.get("text", ""),
                    "metadata": item.get("metadata", {}),
                    "score": 0.0,
                }
            scores[doc_id]["score"] += rrf_score

        merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        return merged

    async def retrieve_for_single_question(
        self,
        query: str,
        document_id: str,
        chapter: int = 0,
        chapters: list[int] | None = None,
        scope_tags: list[str] | None = None,
        top_k: int = 5,
    ) -> RetrievedContext:
        """Retrieve context for a single question (used during partial regeneration)."""
        chapter_scope = []
        if chapters:
            chapter_scope = [
                int(ch)
                for ch in chapters
                if isinstance(ch, int) and int(ch) > 0
            ]
        elif isinstance(chapter, int) and chapter > 0:
            chapter_scope = [chapter]
        elif scope_tags:
            chapter_scope = self._scope_tags_to_chapters(scope_tags)
        fetch_k = top_k if not chapter_scope else max(top_k, top_k * self.MAX_VECTOR_EXPANSION)

        vector_results = await self._safe_vector_search(
            query=query,
            k=fetch_k,
        )

        chunks = []
        for doc, score in vector_results:
            metadata = doc.metadata if isinstance(doc.metadata, dict) else {}
            if chapter_scope and not self._matches_chapters(metadata, chapter_scope):
                continue
            chunks.append(
                {
                    "id": metadata.get("chunk_id", ""),
                    "text": doc.page_content,
                    "metadata": metadata,
                    "score": float(score),
                }
            )
            if len(chunks) >= top_k:
                break

        if len(chunks) < top_k:
            bm25_results = await self._bm25_search(
                query=query,
                document_id=document_id,
                chapters=chapter_scope,
            )
            existing_ids = {chunk["id"] for chunk in chunks}
            for row in bm25_results:
                if row["id"] in existing_ids:
                    continue
                chunks.append(row)
                existing_ids.add(row["id"])
                if len(chunks) >= top_k:
                    break

        return RetrievedContext(
            slot_number=0,
            query=query,
            scope_tags=list(scope_tags or []),
            chunks=chunks,
            combined_text="\n\n---\n\n".join(c["text"] for c in chunks),
        )

    async def _safe_vector_search(self, query: str, k: int) -> list:
        if self.vector_store is None or not hasattr(self.vector_store, "asimilarity_search_with_score"):
            return []

        search_call = self.vector_store.asimilarity_search_with_score(
            query=query,
            k=k,
        )
        timeout_seconds = max(float(settings.VECTOR_SEARCH_TIMEOUT_SECONDS or 0), 0.0)
        try:
            if timeout_seconds > 0:
                return await asyncio.wait_for(search_call, timeout=timeout_seconds)
            return await search_call
        except asyncio.TimeoutError:
            logger.warning(
                "Vector search timed out after %.2fs for query '%s'; falling back to BM25/local retrieval.",
                timeout_seconds,
                self._truncate_query(query),
            )
        except Exception as exc:
            logger.warning(
                "Vector search failed for query '%s'; falling back to BM25/local retrieval: %s",
                self._truncate_query(query),
                exc,
            )
        return []

    def _resolve_chapter_scope(
        self,
        requested_chapters: list[int],
        target_chapter: int | None,
    ) -> list[int]:
        if isinstance(target_chapter, int) and target_chapter > 0:
            return [target_chapter]
        return [ch for ch in requested_chapters if isinstance(ch, int) and ch > 0]

    def _resolve_max_concurrency(self, constraints: dict | None) -> int:
        try:
            value = int((constraints or {}).get("max_concurrency", 1))
        except (TypeError, ValueError):
            value = 1
        return max(1, min(5, value))

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\w+", (text or "").lower())

    def _matches_chapters(self, metadata: dict, chapters: list[int]) -> bool:
        if not chapters:
            return True
        chapter_number = self._extract_chapter_number_from_metadata(metadata)
        return chapter_number in set(chapters)

    def _scope_tags_to_chapters(self, scope_tags: list[str]) -> list[int]:
        chapters: list[int] = []
        for tag in scope_tags:
            if not isinstance(tag, str) or not tag.startswith("chapter:"):
                continue
            _, _, raw_number = tag.partition(":")
            if raw_number.isdigit():
                chapter_number = int(raw_number)
                if chapter_number > 0 and chapter_number not in chapters:
                    chapters.append(chapter_number)
        return chapters

    def _extract_chapter_number_from_metadata(self, metadata: dict) -> int | None:
        if not isinstance(metadata, dict):
            return None

        candidates = [
            metadata.get("chapter_number"),
            metadata.get("chapter"),
            metadata.get("parent_heading"),
        ]
        for value in candidates:
            parsed = self._extract_chapter_number(value)
            if parsed is not None:
                return parsed
        return None

    def _extract_chapter_number(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float):
            parsed = int(value)
            return parsed if parsed > 0 else None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            chapter_match = re.search(
                r"(?i)(?:chapter|chương|phần|part)\s*[:\-]?\s*(\d+)",
                text,
            )
            if chapter_match:
                parsed = int(chapter_match.group(1))
                return parsed if parsed > 0 else None
            standalone = re.fullmatch(r"\d+", text)
            if standalone:
                parsed = int(standalone.group(0))
                return parsed if parsed > 0 else None
        return None

    def _truncate_query(self, query: str, limit: int = 80) -> str:
        normalized = re.sub(r"\s+", " ", str(query or "").strip())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[:limit - 3]}..."


def score_chunk_relatedness(
    primary_chunk: dict,
    candidate_chunk: dict,
    strategy: str = "local_multi",
    primary_idx: int | None = None,
    candidate_idx: int | None = None,
) -> dict:
    """Score how suitable a candidate is as supporting evidence for a primary chunk.

    Designed for chunk assignment/bundling: heading/chapter/lexical signals first,
    optional retrieval score signal when available.
    """
    primary_heading = _normalize_text(_extract_heading(primary_chunk))
    candidate_heading = _normalize_text(_extract_heading(candidate_chunk))
    heading_match = 1.0 if primary_heading and primary_heading == candidate_heading else 0.0

    heading_lexical = _lexical_overlap(primary_heading, candidate_heading)
    topic_overlap = _lexical_overlap(
        _chunk_topic_signature(primary_chunk),
        _chunk_topic_signature(candidate_chunk),
    )

    chapter_match = 1.0 if _extract_chapter(primary_chunk) == _extract_chapter(candidate_chunk) else 0.0

    adjacency = 0.0
    if primary_idx is not None and candidate_idx is not None:
        adjacency = 1.0 / (1.0 + abs(candidate_idx - primary_idx))

    retrieval_score = _normalize_score_signal(_extract_score(candidate_chunk))

    if strategy == "semantic_multi":
        score = (
            0.28 * heading_match
            + 0.22 * topic_overlap
            + 0.18 * heading_lexical
            + 0.12 * chapter_match
            + 0.08 * adjacency
            + 0.12 * retrieval_score
        )
    else:
        score = (
            0.22 * heading_match
            + 0.20 * heading_lexical
            + 0.18 * topic_overlap
            + 0.16 * chapter_match
            + 0.16 * adjacency
            + 0.08 * retrieval_score
        )

    return {
        "score": max(0.0, min(1.0, round(score, 4))),
        "features": {
            "heading_match": round(heading_match, 3),
            "heading_lexical": round(heading_lexical, 3),
            "topic_overlap": round(topic_overlap, 3),
            "chapter_match": round(chapter_match, 3),
            "adjacency": round(adjacency, 3),
            "retrieval_score": round(retrieval_score, 3),
        },
    }


def get_candidate_support_chunks(
    primary_chunk: dict,
    chunk_list: list[dict],
    primary_idx: int | None = None,
    max_candidates: int = 16,
) -> list[dict]:
    """Return candidate support chunks with cheap pre-filtering/ranking."""
    candidates: list[tuple[float, int, dict]] = []
    primary_id = _extract_chunk_id(primary_chunk)
    primary_heading = _normalize_text(_extract_heading(primary_chunk))
    primary_chapter = _extract_chapter(primary_chunk)

    for idx, chunk in enumerate(chunk_list):
        if _extract_chunk_id(chunk) == primary_id:
            continue

        heading = _normalize_text(_extract_heading(chunk))
        chapter = _extract_chapter(chunk)
        heading_match = 1.0 if primary_heading and heading == primary_heading else 0.0
        chapter_match = 1.0 if primary_chapter == chapter else 0.0
        adjacency = 0.0
        if primary_idx is not None:
            adjacency = 1.0 / (1.0 + abs(idx - primary_idx))

        prior = 0.5 * heading_match + 0.3 * chapter_match + 0.2 * adjacency
        candidates.append((prior, idx, chunk))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [item[2] for item in candidates[:max_candidates]]


def rank_supporting_chunks(
    primary_chunk: dict,
    chunk_list: list[dict],
    strategy: str = "local_multi",
    primary_idx: int | None = None,
    max_extra: int = 2,
    enforce_diversity: bool = True,
) -> list[dict]:
    """Rank and select supporting chunks for a primary chunk.

    Returns a list of items:
      [{"chunk": <dict>, "index": <int>, "score": <float>, "features": {...}}]
    """
    candidates = get_candidate_support_chunks(
        primary_chunk=primary_chunk,
        chunk_list=chunk_list,
        primary_idx=primary_idx,
        max_candidates=max(8, max_extra * 6),
    )

    index_map = {_extract_chunk_id(chunk): i for i, chunk in enumerate(chunk_list)}
    scored: list[dict] = []
    for chunk in candidates:
        chunk_id = _extract_chunk_id(chunk)
        idx = index_map.get(chunk_id, -1)
        relatedness = score_chunk_relatedness(
            primary_chunk=primary_chunk,
            candidate_chunk=chunk,
            strategy=strategy,
            primary_idx=primary_idx,
            candidate_idx=idx if idx >= 0 else None,
        )
        scored.append({
            "chunk": chunk,
            "index": idx,
            "score": relatedness["score"],
            "features": relatedness["features"],
            "group_key": _support_group_key(chunk),
        })

    scored.sort(key=lambda item: item["score"], reverse=True)

    selected: list[dict] = []
    seen_groups: set[str] = set()
    for item in scored:
        if enforce_diversity and item["group_key"] in seen_groups and len(scored) > max_extra:
            continue
        selected.append(item)
        seen_groups.add(item["group_key"])
        if len(selected) >= max_extra:
            break

    return selected


def _extract_chunk_id(chunk: dict) -> str:
    return chunk.get("chunk_id") or chunk.get("id") or ""


def _extract_heading(chunk: dict) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return (
        chunk.get("parent_heading")
        or metadata.get("parent_heading")
        or chunk.get("chapter")
        or metadata.get("chapter")
        or ""
    )


def _extract_chapter(chunk: dict) -> Any:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    return chunk.get("chapter") or metadata.get("chapter")


def _extract_score(chunk: dict) -> float | None:
    score = chunk.get("score")
    if isinstance(score, (int, float)):
        return float(score)
    return None


def _chunk_topic_signature(chunk: dict) -> str:
    heading = _normalize_text(_extract_heading(chunk))
    if heading:
        return heading
    content = _normalize_text(chunk.get("content") or chunk.get("chunk_text") or chunk.get("text") or "")
    if not content:
        return "unknown"
    tokens = [token for token in content.split() if len(token) > 3]
    if not tokens:
        tokens = content.split()
    return " ".join(tokens[:8]) if tokens else "unknown"


def _support_group_key(chunk: dict) -> str:
    heading = _normalize_text(_extract_heading(chunk))
    if heading:
        return f"heading:{heading}"
    return f"topic:{_chunk_topic_signature(chunk)}"


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _lexical_overlap(left: str, right: str) -> float:
    left_tokens = set(_normalize_text(left).split())
    right_tokens = set(_normalize_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _normalize_score_signal(score: float | None) -> float:
    if score is None:
        return 0.0
    abs_score = abs(float(score))
    return max(0.0, min(1.0, abs_score / (1.0 + abs_score)))


RetrievalAgent = RetrievalEngine

