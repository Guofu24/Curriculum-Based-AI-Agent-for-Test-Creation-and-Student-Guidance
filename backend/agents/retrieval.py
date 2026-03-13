"""
Retrieval Agent

Responsibilities:
- Hybrid search (vector similarity + BM25 keyword match)
- Filter by chapter, textbook
- Re-rank results for relevance
- Return contextual chunks for each question slot

Storage:
- Pinecone (cloud) — vector similarity search
- PostgreSQL textbook_chunks — BM25 keyword search
"""
from dataclasses import dataclass
from typing import Any
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from rank_bm25 import BM25Okapi

from agents.state import ExamBlueprint, QuestionSlot, RetrievedContext
from models.textbook import TextbookChunk


class RetrievalAgent:
    """
    Retrieves relevant textbook content for question generation.
    Uses hybrid search: Pinecone vector similarity + PostgreSQL BM25 keyword scoring.
    """

    TOP_K_VECTOR = 10  # top results from vector search
    TOP_K_BM25 = 10  # top results from BM25
    FINAL_TOP_K = 5  # final merged results per slot

    def __init__(self, vector_store, db_session: AsyncSession = None):
        self.vector_store = vector_store
        self.db_session = db_session

    async def retrieve_for_blueprint(
        self,
        blueprint: ExamBlueprint,
        textbook_id: str,
        chapters: list[int],
        constraints: dict,
    ) -> list[RetrievedContext]:
        """
        Retrieve relevant context for each question slot in the blueprint.
        """
        contexts = []

        for slot in blueprint.slots:
            context = await self._retrieve_for_slot(
                slot=slot,
                textbook_id=textbook_id,
                chapters=chapters,
                constraints=constraints,
            )
            contexts.append(context)

        return contexts

    async def _retrieve_for_slot(
        self,
        slot: QuestionSlot,
        textbook_id: str,
        chapters: list[int],
        constraints: dict,
    ) -> RetrievedContext:
        """Retrieve context for a single question slot using hybrid search."""

        # Build the search query from slot info
        query = self._build_query(slot)

        # 1. Vector similarity search (async — namespace already isolates by textbook)
        vector_results = await self.vector_store.asimilarity_search_with_score(
            query=query,
            k=self.TOP_K_VECTOR,
        )

        # 2. BM25 keyword search over the same collection
        bm25_results = await self._bm25_search(
            query=query,
            textbook_id=textbook_id,
            chapters=chapters,
        )

        # 3. Merge and re-rank
        merged = self._hybrid_merge(vector_results, bm25_results)

        # 4. Filter by chapter if strict
        if chapters:
            merged = [
                r for r in merged
                if r.get("metadata", {}).get("page", 0) >= 0  # keep all if no page info
            ]

        # Take top results
        top_results = merged[:self.FINAL_TOP_K]

        return RetrievedContext(
            slot_number=slot.slot_number,
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
        parts = []
        if slot.target_topics:
            parts.append(" ".join(slot.target_topics))
        if slot.target_chapter and slot.target_chapter > 0:
            parts.append(f"chapter {slot.target_chapter}")
        parts.append(f"{slot.bloom_level} level question")
        return " ".join(parts)

    async def _bm25_search(
        self,
        query: str,
        textbook_id: str,
        chapters: list[int],
    ) -> list[dict]:
        """BM25 keyword search over chunk text stored in PostgreSQL."""
        if self.db_session is None:
            return []

        import json
        result = await self.db_session.execute(
            select(TextbookChunk).where(TextbookChunk.textbook_id == textbook_id)
        )
        rows = list(result.scalars().all())

        if not rows:
            return []

        documents = [r.content for r in rows]
        chunk_ids = [r.chunk_id for r in rows]
        metadatas = []
        for r in rows:
            try:
                metadatas.append(json.loads(r.metadata_json) if r.metadata_json else {})
            except (json.JSONDecodeError, TypeError):
                metadatas.append({})

        # Tokenize for BM25
        tokenized_corpus = [doc.lower().split() for doc in documents]
        bm25 = BM25Okapi(tokenized_corpus)

        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)

        # Create scored results
        results = []
        for i, score in enumerate(scores):
            results.append({
                "id": chunk_ids[i],
                "text": documents[i],
                "metadata": metadatas[i],
                "score": float(score),
            })

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:self.TOP_K_BM25]

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
        k = 60  # RRF constant

        scores = {}  # id -> {score, text, metadata}

        # Score vector results
        for rank, item in enumerate(vector_results):
            if hasattr(item, '__len__') and len(item) == 2:
                doc, score = item
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

        # Score BM25 results
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

        # Sort by combined RRF score
        merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        return merged

    async def retrieve_for_single_question(
        self,
        query: str,
        textbook_id: str,
        chapter: int,
        top_k: int = 5,
    ) -> RetrievedContext:
        """Retrieve context for a single question (used during partial regeneration)."""
        vector_results = await self.vector_store.asimilarity_search_with_score(
            query=query,
            k=top_k,
        )

        chunks = []
        for doc, score in vector_results:
            chunks.append({
                "id": doc.metadata.get("chunk_id", ""),
                "text": doc.page_content,
                "metadata": doc.metadata,
                "score": float(score),
            })

        return RetrievedContext(
            slot_number=0,
            chunks=chunks,
            combined_text="\n\n---\n\n".join(c["text"] for c in chunks),
        )


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
    # Robust squashing for both cosine-like or BM25-like ranges.
    abs_score = abs(float(score))
    return max(0.0, min(1.0, abs_score / (1.0 + abs_score)))
