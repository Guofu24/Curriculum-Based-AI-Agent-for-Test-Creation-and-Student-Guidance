"""
dispatch_tasks — dynamic task allocation node.

Reads task_queue from state and decides whether to run additional work
(e.g. focused_retrieval for weak chapters) before proceeding to create_outline.

This enables true dynamic task allocation: retrieval results at runtime can
enqueue extra steps that were not in the original static graph plan.
"""

import logging

from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


async def dispatch_tasks(state: ExamGraphState) -> ExamGraphState:
    """
    Check task_queue and route to extra work if needed.

    Current supported task types:
    - focused_retrieval: re-retrieve for specific weak chapters
      (handled inline here by appending supplementary chunks to retrieved_context)

    Returns state with task_queue cleared (tasks are consumed once).
    """
    task_queue: list[dict] = list(state.get("task_queue") or [])
    if not task_queue:
        return state

    exam_id = state.get("exam_id", "")
    retrieved_context = list(state.get("retrieved_context") or [])
    warnings = list(state.get("warnings") or [])
    consumed: list[str] = []

    for task in task_queue:
        task_type = task.get("type")

        if task_type == "focused_retrieval":
            weak_chapters: list[str] = task.get("chapters", [])
            if not weak_chapters:
                consumed.append(task_type)
                continue

            logger.info(
                "[dispatch_tasks] exam=%s: focused_retrieval for weak chapters=%s",
                exam_id, weak_chapters,
            )
            try:
                from app.agents.retrieval import RetrievalAgent
                from app.core.redis_client import get_redis_client

                agent = RetrievalAgent(redis=get_redis_client())
                document_id = state.get("document_id") or ""
                textbook_namespace = state.get("textbook_namespace") or None
                exam_config = state.get("exam_config", {})
                bloom_targets = list(exam_config.get("bloom_distribution", {}).keys())

                if textbook_namespace:
                    result = await agent.retrieve_textbook(
                        textbook_namespace=textbook_namespace,
                        scope_chapters=weak_chapters,
                        bloom_targets=bloom_targets,
                        trace_id=f"{exam_id}_focused",
                    )
                else:
                    result = await agent.retrieve(
                        document_id=document_id,
                        scope_chapters=weak_chapters,
                        bloom_targets=bloom_targets,
                        trace_id=f"{exam_id}_focused",
                    )

                extra_chunks = getattr(result, "retrieved_chunks", [])
                if extra_chunks:
                    # Deduplicate by chunk_id before appending
                    existing_ids = {c.get("chunk_id") for c in retrieved_context}
                    new_chunks = [c for c in extra_chunks if c.get("chunk_id") not in existing_ids]
                    retrieved_context.extend(new_chunks)
                    warnings.append(
                        f"dispatch_tasks: focused_retrieval added {len(new_chunks)} chunks "
                        f"for weak chapters {weak_chapters}"
                    )
                    logger.info(
                        "[dispatch_tasks] exam=%s: +%d chunks from focused_retrieval (chapters=%s)",
                        exam_id, len(new_chunks), weak_chapters,
                    )
            except Exception as exc:
                warnings.append(f"dispatch_tasks: focused_retrieval failed (non-critical): {exc}")
                logger.warning("[dispatch_tasks] focused_retrieval error: %s", exc)

            consumed.append(task_type)

    # Clear consumed tasks
    remaining = [t for t in task_queue if t.get("type") not in consumed]

    return {
        **state,
        "retrieved_context": retrieved_context,
        "task_queue": remaining,
        "warnings": warnings,
    }
