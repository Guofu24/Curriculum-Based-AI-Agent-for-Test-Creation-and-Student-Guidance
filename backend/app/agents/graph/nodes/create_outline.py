"""create_outline — Agent 2: Outline Agent (includes G8 outline_feedback)."""

import logging

from app.agents.graph.state import ExamGraphState, AgentRole
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def create_outline(state: ExamGraphState) -> ExamGraphState:
    """
    Agent 2: Create exam blueprint (sườn đề) from retrieved knowledge.

    Calls OutlineAgent.create_outline() with retrieved_context and exam_config.
    If checkpoint_1_rejection_history is non-empty (G8), injects the last
    rejection feedback as exam_config["outline_feedback"] so LLM regenerates
    the blueprint with teacher feedback incorporated.

    Args:
        state: Must contain retrieved_context, exam_config, blueprint_feedback (optional).

    Returns:
        Updated ExamGraphState with outline_result, blueprint, distribution_summary.
    """
    from app.agents.outline import OutlineAgent
    from app.agents.base import AgentStatus

    outline_agent = OutlineAgent()
    retrieved_context = state.get("retrieved_context", [])
    exam_config = dict(state.get("exam_config", {}))
    exam_id = state.get("exam_id", "")
    cost_report = dict(state.get("cost_report", {}))
    warnings = list(state.get("warnings", []))

    # G8: Inject rejection feedback into exam_config for re-generation
    rejection_history = state.get("checkpoint_1_rejection_history", [])
    if rejection_history:
        last_feedback = rejection_history[-1].get("feedback", "")
        if last_feedback:
            exam_config["outline_feedback"] = last_feedback
            warnings.append("Injecting blueprint rejection feedback for regeneration")

    print(f"[create_outline] exam_id={exam_id}, retrieved_context_chunks={len(retrieved_context)}, calling OutlineAgent...", flush=True)

    # Stream reasoning to frontend
    _emit(state, {
        "type": "reasoning_chunk",
        "step_id": "step-2",
        "chunk": f"Phân tích {len(retrieved_context)} đoạn văn bản từ tài liệu...\n",
    })

    outline_result = await outline_agent.create_outline(
        retrieved_context=retrieved_context,
        exam_config=exam_config,
        trace_id=exam_id,
    )

    blueprint = list(getattr(outline_result, "blueprint", []))
    distribution_summary = dict(getattr(outline_result, "distribution_summary", {}))
    print(f"[create_outline] exam_id={exam_id}, blueprint_slots={len(blueprint)}, distribution={distribution_summary}", flush=True)

    if outline_result.status != AgentStatus.SUCCESS:
        warnings.append(f"Outline creation had issues: {outline_result.status.value}")

    cost_report["outline"] = outline_result.token_usage.model_dump()

    # Emit event via WebSocket
    _emit(state, {
        "type": "outline_created",
        "blueprint_slots": len(blueprint),
        "mcq_count": sum(1 for s in blueprint if s.get("type") != "essay"),
        "essay_count": sum(1 for s in blueprint if s.get("type") == "essay"),
    })
    # Stream blueprint summary to reasoning feed
    _emit(state, {
        "type": "reasoning_chunk",
        "step_id": "step-2",
        "chunk": f"Hoàn tất! Tạo {len(blueprint)} câu ({sum(1 for s in blueprint if s.get('type') != 'essay')} MCQ + {sum(1 for s in blueprint if s.get('type') == 'essay')} Essay).\n",
    })

    return {
        **state,
        "outline_result": {
            "status": outline_result.status.value,
            "blueprint": blueprint,
            "distribution_summary": distribution_summary,
            "warnings": outline_result.warnings or [],
        },
        "blueprint": blueprint,
        "distribution_summary": distribution_summary,
        "cost_report": cost_report,
        "current_agent": AgentRole.OUTLINE,
        "warnings": warnings,
        "updated_at": state.get("updated_at"),
    }
