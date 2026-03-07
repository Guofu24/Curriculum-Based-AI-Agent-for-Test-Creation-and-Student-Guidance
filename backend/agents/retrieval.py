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
