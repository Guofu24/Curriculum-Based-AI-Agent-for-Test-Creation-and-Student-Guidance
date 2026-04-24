"""retrieve_knowledge — Agent 1: Retrieval Agent."""

import logging

from app.agents.graph.state import ExamGraphState, AgentRole
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def retrieve_knowledge(state: ExamGraphState) -> ExamGraphState:
    """
    Agent 1: Retrieve knowledge chunks from Pinecone vector DB.

    Calls RetrievalAgent.retrieve() with document_id, scope_chapters, and bloom_targets.
    Stores retrieved chunks in state["retrieved_context"] for downstream nodes.

    Bug-018 fix in RetrievalAgent: embedding failures are now logged instead of
    silently returning [].

    Args:
        state: Must contain document_id, scope, exam_config, exam_id, redis.

    Returns:
        Updated ExamGraphState with retrieval_result, retrieved_context, allowed_concepts.
    """
    from app.agents.retrieval import RetrievalAgent
    from app.agents.base import AgentStatus

    from app.core.redis_client import get_redis_client
    redis_client = get_redis_client()
    exam_config = state.get("exam_config", {})
    scope = state.get("scope", [])
    document_id = state.get("document_id") or ""
    exam_id = state.get("exam_id", "")
    cost_report = dict(state.get("cost_report", {}))
    warnings = list(state.get("warnings", []))

    retrieval_agent = RetrievalAgent(redis=redis_client)
    bloom_targets = list(exam_config.get("bloom_distribution", {}).keys())

    retrieval_result = await retrieval_agent.retrieve(
        document_id=document_id,
        scope_chapters=scope,
        bloom_targets=bloom_targets,
        trace_id=exam_id,
    )

    retrieved_chunks = getattr(retrieval_result, "retrieved_chunks", [])
    coverage_map = getattr(retrieval_result, "coverage_map", {})

    if retrieval_result.status == AgentStatus.PARTIAL:
        warnings.append("Retrieval returned partial results")
    elif retrieval_result.status == AgentStatus.FAILED:
        warnings.append("Retrieval failed — proceeding with empty context")

    # Build allowed_concepts from chunks for ScopeGuard
    allowed_concepts = [
        c.get("content", "")[:200]
        for c in retrieved_chunks
        if c.get("content")
    ]

    cost_report["retrieval"] = retrieval_result.token_usage.model_dump()

    # Emit event via WebSocket
    _emit(state, {
        "type": "retrieval_completed",
        "status": retrieval_result.status.value,
        "chunks_count": len(retrieved_chunks),
    })

    return {
        **state,
        "retrieval_result": {
            "status": retrieval_result.status.value,
            "retrieved_chunks": retrieved_chunks,
            "coverage_map": coverage_map,
            "warnings": retrieval_result.warnings or [],
        },
        "retrieved_context": retrieved_chunks,
        "allowed_concepts": allowed_concepts,
        "cost_report": cost_report,
        "current_agent": AgentRole.RETRIEVAL,
        "warnings": warnings,
        "updated_at": state.get("updated_at"),
    }

