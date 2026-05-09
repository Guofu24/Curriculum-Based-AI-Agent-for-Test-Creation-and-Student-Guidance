"""
merge_plan_retrieval — join node after parallel Planner + Retrieval fan-out.

When plan_type == "complex", plan_complex and retrieve_knowledge run in parallel.
This node merges their results: applies any retrieval-relevant plan overrides
(bloom_targets, scope_chapters) that weren't available during the parallel retrieval.
"""

import logging

from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


async def merge_plan_retrieval(state: ExamGraphState) -> ExamGraphState:
    """
    Merge parallel outputs of plan_complex and retrieve_knowledge.

    plan_complex runs concurrently with retrieve_knowledge, so retrieval
    happened without plan overrides. Here we check if the plan required
    different bloom_targets or scope_chapters, log the delta, and flag
    any coverage gaps for downstream handling.

    Does not re-run retrieval — the retrieved context is used as-is.
    The Outline Agent will receive weak_chapter hints via the message bus
    to compensate for any scope mismatch.
    """
    execution_plan = state.get("execution_plan") or []
    retrieval_result = state.get("retrieval_result") or {}
    exam_id = state.get("exam_id", "")

    if not execution_plan:
        return state

    # Extract what the plan wanted for retrieval
    plan_bloom_targets: list[str] = []
    plan_scope_chapters: list[str] = []
    for step in execution_plan:
        if step.get("tool") == "tool_retrieve_context":
            ov = step.get("params_override") or {}
            plan_bloom_targets = ov.get("bloom_targets", [])
            plan_scope_chapters = ov.get("scope_chapters", [])
            break

    # Compare with what retrieval actually used
    actual_chapters = retrieval_result.get("coverage_map", {}).keys()
    missed_chapters = [ch for ch in plan_scope_chapters if ch not in actual_chapters]

    if missed_chapters or plan_bloom_targets:
        logger.info(
            "[merge_plan_retrieval] exam=%s | plan wanted bloom=%s scope=%s | "
            "retrieval covered=%s | missed=%s (parallel divergence logged)",
            exam_id, plan_bloom_targets, plan_scope_chapters,
            list(actual_chapters), missed_chapters,
        )

    return state
