"""Retrieval Agent - queries vector DB for knowledge chunks."""

import asyncio
import logging
import time
import uuid
from typing import Any
from uuid import UUID

from app.agents.base import AgentBaseOutput, AgentStatus, AgentMetrics, TokenUsage, RetrievalOutput
from app.agents.llm import get_llm_client

logger = logging.getLogger("app.agents.retrieval")
from app.observability.tracer import get_tracer
from app.rag.vector_store import get_vector_store
from app.rag.embedder import EmbeddingService
from app.rag.structure import normalize_chapter_id
from app.core.redis_client import RedisClient
from app.core.config import get_settings

settings = get_settings()
tracer = get_tracer()

try:
    import tiktoken
    _ENCODING = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENCODING = None


def _build_chapter_id_variants(ch_id: str, position: int) -> list[str]:
    """
    Build a list of alternative chapter_id strings to try when the primary
    ch_id returns 0 results from Pinecone (due to indexing/renumbering mismatch).

    Strategies:
      - If ch_id is numeric (e.g. "ch6"), try the letter form at that position
        (e.g. "ch_e" for 5th scope chapter, position=4).
      - If ch_id is letter-based (e.g. "ch_e"), try numeric variants.
      - Always include ±1 numeric variants in case off-by-one from re-numbering.
    """
    variants: list[str] = [ch_id]

    import re
    num_m = re.match(r"^ch(\d+)$", ch_id)
    letter_m = re.match(r"^ch_([a-z])$", ch_id)

    if num_m:
        n = int(num_m.group(1))
        # ±1 off-by-one from clean_heading_tree re-numbering
        for delta in (-1, 1, -2, 2):
            v = f"ch{n + delta}"
            if v not in variants and int(v[2:]) > 0:
                variants.append(v)
        # Letter form based on position in scope (0-indexed A=ch_a, B=ch_b, …)
        if 0 <= position < 26:
            letter = chr(ord('a') + position)
            variants.append(f"ch_{letter}")
        # Also try letter based on the chapter number itself (1=a, 2=b, …)
        if 1 <= n <= 26:
            letter = chr(ord('a') + n - 1)
            variants.append(f"ch_{letter}")

    elif letter_m:
        letter = letter_m.group(1)
        n = ord(letter) - ord('a') + 1
        variants.append(f"ch{n}")
        # ±1
        for delta in (-1, 1):
            v = f"ch{n + delta}"
            if v not in variants and n + delta > 0:
                variants.append(v)
        # Position-based numeric
        variants.append(f"ch{position + 1}")

    return variants



class RetrievalAgent:
    """
    Agent 1: Retrieval Agent

    Role: Query vector database to get the right knowledge chunks
    based on the selected scope. Output is raw knowledge context
    for the Outline Agent.

    Flow:
    1. Query expansion: generate 3-5 query variants
    2. Parallel sub-queries per chapter → Pinecone namespace
    3. Reranking: CrossEncoder (BAAI/bge-reranker-v2-m3) rerank top-20 → top-8
    4. Merge & deduplicate
    """

    def __init__(self, redis: RedisClient | None = None):
        self.llm = get_llm_client()
        self.vector_store = get_vector_store()
        self.embedder = EmbeddingService(redis)
        self.redis = redis

    @tracer.agent_span("retrieval_agent")
    async def retrieve(
        self,
        document_id: str,
        scope_chapters: list[str],
        bloom_targets: list[str] | None = None,
        query_hints: list[str] | None = None,
        trace_id: str = "",
        scope_sections: list[str] | None = None,
    ) -> RetrievalOutput:
        """Main retrieval method."""
        start_time = time.time()
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []
        trace_id = metrics.trace_id

        try:
            # Step 1: Generate query variants (G11)
            expanded_queries = await self._expand_queries(
                scope_chapters, bloom_targets or [], query_hints or []
            )

            # Domain 7B: Map Bloom level to preferred content types for targeted retrieval
            BLOOM_CONTENT_TYPES = {
                "nhan_biet": ["definition", "theorem"],
                "thong_hieu": ["definition", "explanation"],
                "van_dung": ["example", "exercise", "applied_problem"],
                "van_dung_cao": ["example", "exercise", "applied_problem"],
            }

            # Determine preferred content types based on Bloom targets
            content_types: list[str] | None = None
            if bloom_targets:
                types_set: set[str] = set()
                for bloom in bloom_targets:
                    if bloom in BLOOM_CONTENT_TYPES:
                        types_set.update(BLOOM_CONTENT_TYPES[bloom])
                if types_set:
                    content_types = list(types_set)

            # NOTE: Models (bge-m3 + CrossEncoder) are pre-loaded at server startup
            # via lifespan in main.py — no per-request warmup needed.

            # Step 2: Single document query (no per-chapter namespace split).
            # With single namespace per document, one query retrieves all relevant
            # vectors. We boost top_k to cover all chapters in scope.
            boosted_top_k = settings.RAG_TOP_K_PER_CHAPTER * max(len(scope_chapters), 3)
            all_chunks, retrieval_warnings = await self._parallel_query_chapters(
                document_id=document_id,
                chapters=["_all"],  # Single query to whole document namespace
                expanded_queries=expanded_queries,
                top_k=min(boosted_top_k, 100),  # Cap at 100
                content_types=content_types,
            )
            warnings.extend(retrieval_warnings)

            # Step 2b: Supplement chapters that got 0 chunks from the _all query.
            # This guarantees every scope chapter has at least MIN_CHUNKS_PER_CHAPTER
            # chunks even if they didn't surface in the top-100 semantic results.
            MIN_CHUNKS_PER_CHAPTER = 5
            supplement_chunks, supplement_warnings = await self._supplement_missing_chapters(
                document_id=document_id,
                scope_chapters=scope_chapters,
                existing_chunks=all_chunks,
                expanded_queries=expanded_queries,
                min_per_chapter=MIN_CHUNKS_PER_CHAPTER,
                content_types=content_types,
            )
            if supplement_chunks:
                # Deduplicate by chunk_id before merging
                existing_ids = {c["chunk_id"] for c in all_chunks}
                new_chunks = [c for c in supplement_chunks if c["chunk_id"] not in existing_ids]
                all_chunks.extend(new_chunks)
                logger.info(
                    "Supplemented %d chunks for under-represented scope chapters",
                    len(new_chunks),
                )
            warnings.extend(supplement_warnings)

            # Step 3: Rerank — guarantee scope chapters BEFORE token budget cut.
            #
            # Bug fix: the old per-chapter rerank grouped ALL chunks (from all 29
            # chapters in the document), then divided budget equally. With 29 chapters
            # sharing RAG_TOP_K_AFTER_RERANK=30, scope chapters got ~1 chunk each,
            # and _enforce_token_budget later cut them entirely when sorting by score.
            #
            # Fix: (1) normalize scope_chapter IDs once, (2) separate scope vs
            # non-scope chunks, (3) guarantee each scope chapter >= MIN_SCOPE_CHUNKS
            # before the token-budget cut, (4) only fill remaining budget with
            # non-scope chunks.
            rerank_total = settings.RAG_TOP_K_AFTER_RERANK  # e.g. 30
            MIN_SCOPE_CHUNKS = 5  # minimum chunks per scope chapter

            # Normalize scope chapter IDs once (handles ch18 → ch18, roman numerals, etc.)
            scope_ch_ids: set[str] = set()
            for ch in scope_chapters:
                nid = normalize_chapter_id(ch)
                scope_ch_ids.add(nid)
                scope_ch_ids.add(ch)  # also keep original string

            # Separate scope vs non-scope chunks
            scope_chunks: list[dict] = []
            non_scope_chunks: list[dict] = []
            scope_seen: set[str] = set()  # track chunk_ids to avoid duplicates
            non_scope_seen: set[str] = set()

            for chunk in all_chunks:
                ch_raw = chunk.get("metadata", {}).get("chapter", "")
                ch_id = normalize_chapter_id(ch_raw)
                # Also check raw chapter string directly
                is_scope = ch_id in scope_ch_ids or ch_raw in scope_ch_ids
                chunk_id = chunk.get("chunk_id", "")
                if is_scope:
                    if chunk_id not in scope_seen:
                        scope_seen.add(chunk_id)
                        scope_chunks.append(chunk)
                else:
                    if chunk_id not in non_scope_seen:
                        non_scope_seen.add(chunk_id)
                        non_scope_chunks.append(chunk)

            # Per-scope-chapter rerank: keep top-N per chapter (but at least MIN_SCOPE_CHUNKS)
            num_scope = max(len(scope_ch_ids), 1)
            per_scope_k = max(rerank_total // num_scope, MIN_SCOPE_CHUNKS)

            logger.info(
                "Rerank: %d scope chunks across %d scope chapters (top %d each), "
                "%d non-scope chunks (global pool)",
                len(scope_chunks), num_scope, per_scope_k, len(non_scope_chunks),
            )

            # Group scope chunks by normalized chapter_id
            scope_by_ch: dict[str, list[dict]] = {}
            for chunk in scope_chunks:
                ch_id = normalize_chapter_id(chunk.get("metadata", {}).get("chapter", ""))
                if ch_id not in scope_by_ch:
                    scope_by_ch[ch_id] = []
                scope_by_ch[ch_id].append(chunk)

            # Rerank each scope chapter independently
            query_text = " ".join(expanded_queries)
            reranked_scope: list[dict] = []
            for ch_id, ch_chunks in scope_by_ch.items():
                if len(ch_chunks) <= per_scope_k:
                    reranked_scope.extend(ch_chunks)
                else:
                    reranked = await self._rerank_chunks(
                        query=query_text,
                        chunks=ch_chunks,
                        top_k=per_scope_k,
                    )
                    reranked_scope.extend(reranked)

            # Remaining budget after scope chapters
            remaining_budget = rerank_total - len(reranked_scope)
            if remaining_budget > 0 and non_scope_chunks:
                # Sort non-scope by score, keep top remaining_budget
                non_scope_sorted = sorted(
                    non_scope_chunks, key=lambda c: c.get("score", 0), reverse=True
                )
                reranked_scope.extend(non_scope_sorted[:remaining_budget])

            all_chunks = reranked_scope

            # Enforce token budget cap (Phase 1 guard)
            all_chunks, token_warning = self._enforce_token_budget(
                all_chunks, max_tokens=settings.MAX_CONTEXT_TOKENS
            )
            if token_warning:
                warnings.append(token_warning)

            # ── Section filter: keep only chunks whose section matches scope_sections ──
            if scope_sections:
                scope_sec_set = set(s.strip().lower() for s in scope_sections if s.strip())
                if scope_sec_set:
                    filtered_chunks: list[dict] = []
                    for chunk in all_chunks:
                        chunk_sec = (chunk.get("metadata", {}).get("section") or "").strip().lower()
                        if chunk_sec and chunk_sec in scope_sec_set:
                            filtered_chunks.append(chunk)
                    logger.info(
                        "[retrieve] scope_sections=%r → filtered %d chunks (from %d)",
                        list(scope_sec_set), len(filtered_chunks), len(all_chunks),
                    )
                    if filtered_chunks:
                        all_chunks = filtered_chunks
                    # If filtering removed everything, warn but keep chunks (fallback)

            # Build coverage map
            coverage_map: dict[str, list[str]] = {}
            for chunk in all_chunks:
                ch = chunk.get("metadata", {}).get("chapter", "unknown")
                if ch not in coverage_map:
                    coverage_map[ch] = []
                coverage_map[ch].append(chunk["chunk_id"])

            # Step 4: Build response
            retrieved_chunks = [
                {
                    "chunk_id": c["chunk_id"],
                    "chapter": c["metadata"].get("chapter", ""),
                    "chapter_id": c["metadata"].get("chapter_id", ""),
                    "section": c["metadata"].get("section", ""),
                    "content": c["metadata"].get("content", ""),
                    "content_type": c["metadata"].get("content_type", "text"),
                    "relevance_score": c.get("score", 0.0),
                    "latex_repr": c["metadata"].get("latex_repr"),
                }
                for c in all_chunks
            ]

            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = metrics.prompt_tokens + metrics.completion_tokens

            return RetrievalOutput(
                status=AgentStatus.SUCCESS if retrieved_chunks else AgentStatus.PARTIAL,
                agent_name="retrieval",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(
                    prompt_tokens=metrics.prompt_tokens,
                    completion_tokens=metrics.completion_tokens,
                    total_tokens=usage,
                ),
                warnings=warnings,
                trace_id=trace_id,
                retrieved_chunks=retrieved_chunks,
                coverage_map=coverage_map,
            )

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            warnings.append(f"Retrieval failed: {str(e)}. Returning empty context.")

            return RetrievalOutput(
                status=AgentStatus.PARTIAL,
                agent_name="retrieval",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                retrieved_chunks=[],
                coverage_map={},
            )

    # ── G11: Query expansion ─────────────────────────────────────────────────────

    async def _expand_queries(
        self,
        chapters: list[str],
        bloom_targets: list[str],
        hints: list[str],
    ) -> list[str]:
        """
        Generate 3-5 query variants from bloom_target + chapter using GPT-4o-mini.
        G11: Query expansion for better recall.
        """
        prompt = f"""Bạn là chuyên gia tạo câu truy vấn cho hệ thống RAG.
Tạo 3-5 câu truy vấn khác nhau để tìm kiếm kiến thức cho việc sinh câu hỏi.

Chapters: {', '.join(chapters)}
Bloom targets: {', '.join(bloom_targets) if bloom_targets else 'all'}
Query hints: {', '.join(hints) if hints else 'none'}

Tạo các câu truy vấn đa dạng, bao gồm:
- Câu truy vấn tổng quát về chapter
- Câu truy vấn cụ thể về công thức/khái niệm
- Câu truy vấn cho các mức Bloom cao (van_dung, van_dung_cao)

Trả về JSON:
{{"queries": ["query 1", "query 2", "query 3", "query 4", "query 5"]}}"""

        try:
            response = await self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                role="planner",
                max_tokens=500,
                temperature=0.3,
            )

            import json
            data = json.loads(response)

            queries = data.get("queries", [])
            # Always include the original chapter names
            queries.extend(chapters)
            return queries[:5]  # Max 5 queries

        except Exception:
            # Fallback: just use chapter names
            return chapters[:3]

    # ── G10: Parallel chapter retrieval ─────────────────────────────────────────

    async def _parallel_query_chapters(
        self,
        document_id: str,
        chapters: list[str],
        expanded_queries: list[str],
        top_k: int = 20,
        content_types: list[str] | None = None,
    ) -> tuple[list[dict], list[str]]:
        """
        Retrieve chunks from all chapters in parallel.
        G10: Uses asyncio.gather(return_exceptions=True) so 1 chapter failure
        doesn't fail the entire retrieval — logs warning and continues.
        Domain 2B: Each chapter query has a hard 5-second timeout.

        Special case: if chapters=["_all"], skip filter to retrieve from entire doc.
        """
        CHAPTER_TIMEOUT = 30.0  # seconds — needs headroom for embedding + Pinecone query

        is_all = len(chapters) == 1 and chapters[0] == "_all"

        async def _query_one_with_timeout(chapter: str, position: int) -> tuple[str, list[dict] | Exception]:
            """Query one chapter with hard timeout."""
            try:
                if is_all:
                    # _all: query entire document without chapter filter
                    query_text = " ".join(expanded_queries[:3])
                    embedding = await self.embedder.embed_text(query_text)
                    results = await self.vector_store.query_namespace(
                        doc_id=document_id,
                        chapter_id="_all",
                        query_embedding=embedding,
                        top_k=top_k,
                        content_types=content_types,
                    )
                    return chapter, results
                else:
                    result = await asyncio.wait_for(
                        self._retrieve_for_chapter(
                            document_id=document_id,
                            chapter=chapter,
                            queries=expanded_queries,
                            top_k=top_k,
                            content_types=content_types,
                            position=position,
                        ),
                        timeout=CHAPTER_TIMEOUT,
                    )
                    return chapter, result
            except asyncio.TimeoutError:
                return chapter, TimeoutError(f"Chapter '{chapter}' retrieval timed out after {CHAPTER_TIMEOUT}s")
            except Exception as e:
                return chapter, e

        tasks = [_query_one_with_timeout(ch, i) for i, ch in enumerate(chapters)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_chunks: list[dict] = []
        warnings: list[str] = []

        for result in results:
            if isinstance(result, Exception):
                warnings.append(f"Chapter retrieval raised exception: {str(result)}")
                continue
            chapter, chunks_or_error = result
            if isinstance(chunks_or_error, Exception):
                warnings.append(f"Chapter '{chapter}' retrieval failed: {str(chunks_or_error)}")
                continue
            all_chunks.extend(chunks_or_error)

        return all_chunks, warnings

    async def _supplement_missing_chapters(
        self,
        document_id: str,
        scope_chapters: list[str],
        existing_chunks: list[dict],
        expanded_queries: list[str],
        min_per_chapter: int = 5,
        content_types: list[str] | None = None,
    ) -> tuple[list[dict], list[str]]:
        """
        For each scope chapter that has fewer than min_per_chapter chunks in
        existing_chunks, do a targeted Pinecone query filtered by chapter_id
        to guarantee coverage.

        Uses Pinecone metadata filter {"chapter_id": {"$eq": ch_id}} so only
        vectors from that specific chapter are returned.
        """
        warnings: list[str] = []
        supplement: list[dict] = []

        # Count existing coverage per normalized chapter_id
        coverage: dict[str, int] = {}
        for chunk in existing_chunks:
            ch_id = chunk.get("metadata", {}).get("chapter_id", "")
            coverage[ch_id] = coverage.get(ch_id, 0) + 1

        # Generate embedding once (reused for all missing chapters)
        query_text = " ".join(expanded_queries[:3])
        try:
            embedding = await self.embedder.embed_text(query_text)
        except Exception as exc:
            warnings.append(f"Supplement embedding failed: {exc}")
            return supplement, warnings

        for chapter in scope_chapters:
            ch_id = normalize_chapter_id(chapter)
            existing_count = coverage.get(ch_id, 0)
            if existing_count >= min_per_chapter:
                continue  # Already has enough chunks

            need = min_per_chapter - existing_count
            logger.info(
                "[supplement] chapter=%r (ch_id=%r) has %d chunks, fetching %d more",
                chapter, ch_id, existing_count, need,
            )

            # Use chapter-specific embedding for better relevance
            chapter_query = f"{chapter} {' '.join(expanded_queries[:2])}"
            try:
                        ch_embedding = await self.embedder.embed_text(chapter_query)
            except Exception:
                ch_embedding = embedding  # Fallback to generic embedding

            try:
                results = await self.vector_store.query_namespace(
                    doc_id=document_id,
                    chapter_id=ch_id,
                    query_embedding=ch_embedding,
                    top_k=max(need * 2, 10),
                    content_types=content_types,
                    filter_metadata={"chapter_id": {"$eq": ch_id}},
                )
                if results:
                    supplement.extend(results)
                    logger.info(
                        "[supplement] chapter=%r → fetched %d chunks via chapter_id filter",
                        chapter, len(results),
                    )
                else:
                    # 0 results — possibly indexed with a different chapter_id
                    # (e.g. "ch_e" instead of "ch6" due to heading tree renumbering).
                    pos = scope_chapters.index(chapter) if chapter in scope_chapters else 0
                    fallback_ids = _build_chapter_id_variants(ch_id, pos)
                    logger.info(
                        "[supplement] chapter=%r → 0 results, trying variants: %s",
                        chapter, fallback_ids,
                    )
                    found_alt = False
                    for alt_id in fallback_ids:
                        if alt_id == ch_id:
                            continue
                        alt_results = await self.vector_store.query_namespace(
                            doc_id=document_id,
                            chapter_id=alt_id,
                            query_embedding=ch_embedding,
                            top_k=max(need * 2, 10),
                            content_types=content_types,
                            filter_metadata={"chapter_id": {"$eq": alt_id}},
                        )
                        if alt_results:
                            supplement.extend(alt_results)
                            logger.info(
                                "[supplement] chapter=%r → fetched %d chunks via alt_id=%r",
                                chapter, len(alt_results), alt_id,
                            )
                            found_alt = True
                            break
                    if not found_alt:
                        warnings.append(
                            f"Chapter '{chapter}' (ch_id={ch_id!r}) returned 0 chunks even with "
                            "targeted filter — may not be indexed."
                        )
            except Exception as exc:
                warnings.append(f"Supplement query failed for chapter '{chapter}': {exc}")

        return supplement, warnings

    # ── Token budget guard ─────────────────────────────────────────────────────

    def _enforce_token_budget(
        self,
        chunks: list[dict],
        max_tokens: int = 3000,
    ) -> tuple[list[dict], str | None]:
        """
        Truncate chunks so total token count stays within max_tokens.

        Strategy:
        - If tiktoken is available: count tokens precisely.
        - If chunks have relevance scores: sort descending, truncate.
        - Otherwise: character heuristic (1 token ≈ 4 chars).

        Returns (truncated_chunks, warning_or_none).
        """
        if not chunks:
            return chunks, None

        warning = None

        if _ENCODING is not None:
            total_tokens = sum(
                len(_ENCODING.encode(c.get("content", "")))
                for c in chunks
            )
        else:
            # Fallback heuristic: 1 token ≈ 4 chars
            total_tokens = sum(len(c.get("content", "")) // 4 for c in chunks)

        if total_tokens <= max_tokens:
            return chunks, None

        warning = (
            f"Token budget exceeded: {total_tokens} tokens > {max_tokens} limit. "
            f"Truncating to top-scoring chunks."
        )

        if _ENCODING is not None:
            # Sort by score descending (keep highest-relevance chunks)
            scored = [c for c in chunks if c.get("score", 0) > 0]
            unsorted_rest = [c for c in chunks if c not in scored]
            scored.sort(key=lambda c: c.get("score", 0), reverse=True)

            kept: list[dict] = []
            running_tokens = 0
            for c in scored + unsorted_rest:
                c_tokens = len(_ENCODING.encode(c.get("content", "")))
                if running_tokens + c_tokens <= max_tokens:
                    kept.append(c)
                    running_tokens += c_tokens
                else:
                    break
            return kept, warning
        else:
            # No tiktoken + no scores: character heuristic truncate
            char_limit = max_tokens * 4
            kept: list[dict] = []
            running_chars = 0
            for c in chunks:
                content = c.get("content", "")
                if running_chars + len(content) <= char_limit:
                    kept.append(c)
                    running_chars += len(content)
                else:
                    # Truncate the last chunk to fit
                    remaining = char_limit - running_chars
                    if remaining > 50:
                        truncated = c.copy()
                        truncated["content"] = content[:remaining]
                        kept.append(truncated)
                    break
            return kept, warning

    async def _retrieve_for_chapter(
        self,
        document_id: str,
        chapter: str,
        queries: list[str],
        top_k: int = 20,
        content_types: list[str] | None = None,
        position: int = 0,
    ) -> list[dict]:
        """Retrieve chunks for a specific chapter using Pinecone metadata filter + variants fallback."""
        chapter_chunks = []

        chapter_id = normalize_chapter_id(chapter)

        # Check if chapter is in scope_chapters for position lookup
        logger.info(
            "[_retrieve_for_chapter] doc=%s, chapter_input='%s', chapter_id='%s'",
            document_id, chapter, chapter_id,
        )

        # Generate embedding for the query
        query_text = " ".join(queries[:3])
        try:
            embedding = await self.embedder.embed_text(query_text)
        except Exception as exc:
            logger.warning(
                "Embedding failed for chapter=%s doc=%s: %s",
                chapter, document_id, exc,
            )
            return []

        # ── Primary query with Pinecone chapter_id filter ──
        results = await self.vector_store.query_namespace(
            doc_id=document_id,
            chapter_id=chapter_id,
            query_embedding=embedding,
            top_k=top_k,
            content_types=content_types,
            filter_metadata={"chapter_id": {"$eq": chapter_id}},
        )

        if results:
            logger.info(
                "[_retrieve_for_chapter] doc=%s, chapter_id='%s' → %d results (filtered)",
                document_id, chapter_id, len(results),
            )
            chapter_chunks.extend(results)
        else:
            # ── Fallback: try chapter_id variants (renumbering mismatch) ──
            variants = _build_chapter_id_variants(chapter_id, position)
            logger.info(
                "[_retrieve_for_chapter] chapter_id='%s' → 0 results, trying variants: %s",
                chapter_id, variants,
            )
            for alt_id in variants:
                if alt_id == chapter_id:
                    continue
                alt_results = await self.vector_store.query_namespace(
                    doc_id=document_id,
                    chapter_id=alt_id,
                    query_embedding=embedding,
                    top_k=top_k,
                    content_types=content_types,
                    filter_metadata={"chapter_id": {"$eq": alt_id}},
                )
                if alt_results:
                    logger.info(
                        "[_retrieve_for_chapter] alt_id='%s' → %d results",
                        alt_id, len(alt_results),
                    )
                    chapter_chunks.extend(alt_results)
                    break

        return chapter_chunks

    async def _rerank_chunks(
        self,
        query: str,
        chunks: list[dict],
        top_k: int = 8,
    ) -> list[dict]:
        """Rerank chunks using local CrossEncoder (BAAI/bge-reranker-v2-m3)."""
        if not chunks:
            return []

        # Prepare candidate texts (no [index] prefix needed for cross-encoder)
        candidates = [c["metadata"].get("content", "") for c in chunks]

        try:
            reranked_indices = await self.embedder.rerank(
                query=query,
                candidates=candidates,
                top_k=top_k,
            )

            # Reorder chunks based on reranking
            reranked = []
            seen_ids = set()
            for idx, score in reranked_indices:
                if not isinstance(idx, int) or not (0 <= idx < len(chunks)):
                    continue
                chunk = chunks[idx]
                if chunk["chunk_id"] not in seen_ids:
                    chunk["score"] = float(score)
                    reranked.append(chunk)
                    seen_ids.add(chunk["chunk_id"])

            # Add remaining chunks not in rerank results
            for chunk in chunks:
                if chunk["chunk_id"] not in seen_ids:
                    reranked.append(chunk)
                    seen_ids.add(chunk["chunk_id"])

            return reranked[:top_k]

        except Exception:
            # Fallback: return top-k by original score
            sorted_chunks = sorted(chunks, key=lambda x: x.get("score", 0), reverse=True)
            return sorted_chunks[:top_k]
