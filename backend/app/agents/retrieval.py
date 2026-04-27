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

            # Step 2: Parallel retrieval per chapter — G10 + Domain 2B (5s timeout)
            all_chunks, retrieval_warnings = await self._parallel_query_chapters(
                document_id=document_id,
                chapters=scope_chapters,
                expanded_queries=expanded_queries,
                top_k=settings.RAG_TOP_K_PER_CHAPTER,
                content_types=content_types,
            )
            warnings.extend(retrieval_warnings)

            # Enforce token budget cap (Phase 1 guard)
            all_chunks, token_warning = self._enforce_token_budget(
                all_chunks, max_tokens=settings.MAX_CONTEXT_TOKENS
            )
            if token_warning:
                warnings.append(token_warning)

            # Build coverage map
            coverage_map: dict[str, list[str]] = {}
            for chunk in all_chunks:
                ch = chunk.get("metadata", {}).get("chapter", "unknown")
                if ch not in coverage_map:
                    coverage_map[ch] = []
                coverage_map[ch].append(chunk["chunk_id"])

            # Step 3: Rerank and dedupe
            if len(all_chunks) > settings.RAG_TOP_K_AFTER_RERANK:
                all_chunks = await self._rerank_chunks(
                    query=" ".join(expanded_queries),
                    chunks=all_chunks,
                    top_k=settings.RAG_TOP_K_AFTER_RERANK,
                )

            # Step 4: Build response
            retrieved_chunks = [
                {
                    "chunk_id": c["chunk_id"],
                    "chapter": c["metadata"].get("chapter", ""),
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
        """
        CHAPTER_TIMEOUT = 5.0  # seconds

        async def _query_one_with_timeout(chapter: str) -> tuple[str, list[dict] | Exception]:
            """Query one chapter with hard timeout."""
            try:
                result = await asyncio.wait_for(
                    self._retrieve_for_chapter(
                        document_id=document_id,
                        chapter=chapter,
                        queries=expanded_queries,
                        top_k=top_k,
                        content_types=content_types,
                    ),
                    timeout=CHAPTER_TIMEOUT,
                )
                return chapter, result
            except asyncio.TimeoutError:
                return chapter, TimeoutError(f"Chapter '{chapter}' retrieval timed out after {CHAPTER_TIMEOUT}s")
            except Exception as e:
                return chapter, e

        tasks = [_query_one_with_timeout(ch) for ch in chapters]
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
    ) -> list[dict]:
        """Retrieve chunks for a specific chapter."""
        chapter_chunks = []

        chapter_id = normalize_chapter_id(chapter)

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

        # Query Pinecone — use query_namespace (doc_id + chapter_id, not document_id + chapter_ids)
        results = await self.vector_store.query_namespace(
            doc_id=document_id,
            chapter_id=chapter_id,
            query_embedding=embedding,
            top_k=top_k,
            content_types=content_types,
        )

        chapter_chunks.extend(results)

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
