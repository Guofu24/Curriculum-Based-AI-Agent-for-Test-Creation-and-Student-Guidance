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
    print(f"[create_outline] exam_id={exam_id}, rejection_history_len={len(rejection_history)}, entries={[r.get('feedback','')[:60] for r in rejection_history]}", flush=True)
    if rejection_history:
        last_feedback = rejection_history[-1].get("feedback", "")
        if last_feedback:
            exam_config["outline_feedback"] = last_feedback
            # Pass the current blueprint so LLM can modify it (not generate from scratch)
            current_blueprint = state.get("blueprint", [])
            if current_blueprint:
                exam_config["current_blueprint"] = current_blueprint
            warnings.append("Injecting blueprint rejection feedback for regeneration")
            print(f"[create_outline] FEEDBACK INJECTED (from state): {last_feedback[:100]}", flush=True)
    else:
        # Fallback: read from Redis in case LangGraph state didn't persist rejection_history
        try:
            from app.core.redis_client import get_redis_client
            import json as _json
            _redis = get_redis_client()
            _key = f"hitl:rejected:{exam_id}:1"
            _raw = await _redis.get(_key)
            if _raw:
                _data = _json.loads(_raw) if isinstance(_raw, str) else _raw
                _feedback = _data.get("feedback", "")
                if _feedback:
                    exam_config["outline_feedback"] = _feedback
                    current_blueprint = state.get("blueprint", [])
                    if current_blueprint:
                        exam_config["current_blueprint"] = current_blueprint
                    warnings.append("Injecting blueprint rejection feedback from Redis fallback")
                    print(f"[create_outline] FEEDBACK INJECTED (from Redis): {_feedback[:100]}", flush=True)
        except Exception as _e:
            print(f"[create_outline] Redis fallback failed: {_e}", flush=True)

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
