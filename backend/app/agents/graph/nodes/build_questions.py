"""build_questions — Agent 3: Builder Agent."""

import logging

from app.agents.graph.state import ExamGraphState, AgentRole
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def build_questions(state: ExamGraphState) -> ExamGraphState:
    """
    Agent 3: Generate actual questions from blueprint slots.

    Calls BuilderAgent.build() with the blueprint, retrieved context, and retry_issues.
    If retry_issues is non-empty, Builder filters out already-good slots and only
    regenerates the bad ones.

    Bug-020 fix in BuilderAgent: demo question fallback uses chapter + topic_hint
    from the slot when context is empty.

    Args:
        state: Must contain blueprint, retrieved_context, topics_used,
               allowed_concepts, scope, retry_issues, exam_id.

    Returns:
        Updated ExamGraphState with builder_result, questions, topics_used.
    """
    from app.agents.builder import BuilderAgent

    from app.core.redis_client import get_redis_client
    redis_client = get_redis_client()
    blueprint = state.get("blueprint", [])
    retrieved_context = state.get("retrieved_context", [])
    topics_used = list(state.get("topics_used", []))
    allowed_concepts = state.get("allowed_concepts", [])
    scope = state.get("scope", [])
    exam_config = state.get("exam_config", {})
    exam_id = state.get("exam_id", "")
    cost_report = dict(state.get("cost_report", {}))
    warnings = list(state.get("warnings", []))
    questions = list(state.get("questions", []))
    retry_issues = state.get("retry_issues", [])

    builder_agent = BuilderAgent(redis_client=redis_client)

    # Filter blueprint: if retry_issues exists, exclude good slots
    if retry_issues:
        bad_ids = {issue["question_id"] for issue in retry_issues}
        filtered_blueprint = [
            s for s in blueprint
            if s.get("question_id") in bad_ids
        ]
        logger.info("Retry mode: rebuilding %d slots (filtering %d good slots)", len(filtered_blueprint), len(blueprint) - len(filtered_blueprint))
    else:
        filtered_blueprint = blueprint

    # Emit reasoning start
    total = len(filtered_blueprint)
    _emit(state, {
        "type": "reasoning_chunk",
        "step_id": "step-3",
        "chunk": f"Bắt đầu sinh {total} câu hỏi từ blueprint...\n",
    })

    builder_result = await builder_agent.build(
        blueprint=filtered_blueprint,
        retrieved_context=retrieved_context,
        topics_used=topics_used,
        allowed_concepts=allowed_concepts,
        scope_chapters=scope,
        trace_id=exam_id,
    )

    new_questions = list(getattr(builder_result, "questions", []))

    # If retry, merge new questions with existing questions
    if retry_issues and questions:
        new_q_dict = {q.get("question_id"): q for q in new_questions}
        merged = []
        for q in questions:
            qid = q.get("question_id")
            if qid in new_q_dict:
                merged.append(new_q_dict[qid])  # Use rebuilt question
            else:
                merged.append(q)  # Keep original
        questions = merged
    elif not retry_issues:
        questions = new_questions

    # Update topics
    new_topics = [q.get("topic_hint", "") for q in questions if q.get("topic_hint")]
    topics_used = list(set(topics_used + new_topics))

    # Emit question_generated events with progress
    for qi, q in enumerate(questions):
        _emit(state, {
            "type": "reasoning_chunk",
            "step_id": "step-3",
            "chunk": f"[✓] Câu {qi+1}/{len(questions)}: {(q.get('stem') or q.get('content', ''))[:80]}...\n",
        })
        _emit(state, {
            "type": "question_generated",
            "question_id": q.get("question_id", ""),
            "question": q,
        })

    cost_report["builder"] = builder_result.token_usage.model_dump()

    return {
        **state,
        "builder_result": {
            "status": builder_result.status.value,
            "questions": questions,
            "topics_used": topics_used,
            "warnings": builder_result.warnings or [],
        },
        "questions": questions,
        "topics_used": topics_used,
        "cost_report": cost_report,
        "current_agent": AgentRole.BUILDER,
        "warnings": warnings + (builder_result.warnings or []),
        "updated_at": state.get("updated_at"),
    }

