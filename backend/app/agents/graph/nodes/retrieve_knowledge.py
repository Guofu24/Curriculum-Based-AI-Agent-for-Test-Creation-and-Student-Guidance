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
    textbook_namespace = state.get("textbook_namespace") or None

    # Expand scope with prerequisite chapters (BFS for transitive deps)
    # prereq_chapters are passed separately to retrieval — they provide background context
    # but are NOT used for question generation scope (section filter still applies to primary scope).
    scope_sections = list(exam_config.get("scope_sections") or [])
    prereq_chapters: list[str] = []
    if document_id and scope and not textbook_namespace:
        try:
            import uuid as _uuid
            from app.core.database import async_session_maker
            from sqlalchemy import select
            from app.models.document import Document
            async with async_session_maker() as _session:
                _doc_uuid = _uuid.UUID(document_id) if isinstance(document_id, str) else document_id
                _result = await _session.execute(select(Document).where(Document.id == _doc_uuid))
                _doc = _result.scalar_one_or_none()
                if _doc and _doc.heading_tree:
                    prereq_graph = _doc.heading_tree.get("prerequisites", {})
                    # BFS to collect all transitive prerequisites
                    visited: set[str] = set(scope)
                    queue = list(scope)
                    while queue:
                        ch = queue.pop(0)
                        for prereq in prereq_graph.get(ch, []):
                            if prereq not in visited:
                                visited.add(prereq)
                                queue.append(prereq)
                                prereq_chapters.append(prereq)
                    if prereq_chapters:
                        logger.info(
                            "[retrieve_knowledge] exam=%s: prereq chapters (transitive) %s",
                            exam_id, prereq_chapters,
                        )
        except Exception as _e:
            logger.debug("[retrieve_knowledge] prerequisite expansion skipped: %s", _e)

    # Apply PlannerAgent overrides (only when plan_type == "complex")
    _plan = state.get("execution_plan") or []
    for _step in _plan:
        if _step.get("tool") == "tool_retrieve_context":
            _ov = _step.get("params_override") or {}
            if _ov.get("bloom_targets"):
                bloom_targets = list(_ov["bloom_targets"])
                logger.info("execution_plan override: bloom_targets=%s for exam %s", bloom_targets, exam_id)
            break

    # Stream reasoning start
    scope_str = ', '.join(scope) if scope else 'toàn bộ'
    source_label = f"namespace '{textbook_namespace}'" if textbook_namespace else f"document {document_id or '?'}"
    _emit(state, {
        "type": "reasoning_chunk",
        "step_id": "step-1",
        "chunk": f"Tìm kiếm kiến thức từ {source_label} trong phạm vi: {scope_str}\n",
    })

    if textbook_namespace:
        retrieval_result = await retrieval_agent.retrieve_textbook(
            textbook_namespace=textbook_namespace,
            scope_chapters=scope,
            bloom_targets=bloom_targets,
            trace_id=exam_id,
            scope_sections=scope_sections,
        )
    else:
        retrieval_result = await retrieval_agent.retrieve(
            document_id=document_id,
            scope_chapters=scope,
            bloom_targets=bloom_targets,
            trace_id=exam_id,
            scope_sections=scope_sections,
            prereq_chapters=prereq_chapters or None,
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

    # Stream reasoning result
    _emit(state, {
        "type": "reasoning_chunk",
        "step_id": "step-1",
        "chunk": f"Tìm thấy {len(retrieved_chunks)} đoạn văn bản liên quan.\n",
    })

    # Fix 3: dynamically enqueue focused_retrieval task for weak chapters
    task_queue = list(state.get("task_queue") or [])
    if coverage_map:
        weak_chapters = [
            ch for ch, cov in coverage_map.items()
            if isinstance(cov, (int, float)) and cov < 0.3
        ]
        if weak_chapters:
            task_queue.append({"type": "focused_retrieval", "chapters": weak_chapters})
            logger.info(
                "[retrieve_knowledge] exam=%s: enqueued focused_retrieval for weak chapters=%s",
                exam_id, weak_chapters,
            )

    # Publish coverage report directly to OutlineAgent via message bus (peer-to-peer)
    try:
        from app.agents.messaging import AgentMessageBus
        bus = AgentMessageBus(redis_client)
        await bus.publish(
            exam_id=exam_id,
            sender="retrieval",
            recipient="outline",
            message_type="coverage_report",
            payload={
                "coverage_map": coverage_map,
                "chunk_count": len(retrieved_chunks),
                "chapters_covered": list(coverage_map.keys()),
                "weak_chapters": [
                    ch for ch, cov in coverage_map.items()
                    if isinstance(cov, (int, float)) and cov < 0.3
                ],
            },
        )
    except Exception as _e:
        logger.debug("coverage_report publish failed (non-critical): %s", _e)

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
        "task_queue": task_queue,
        "cost_report": cost_report,
        "current_agent": AgentRole.RETRIEVAL,
        "warnings": warnings,
        "updated_at": state.get("updated_at"),
    }

