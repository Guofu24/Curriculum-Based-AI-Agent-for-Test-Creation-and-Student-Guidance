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

    Also maintains blueprint_history so the outline agent can see all
    previously generated blueprints across rejection cycles.

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

    # Apply PlannerAgent overrides into exam_config (only when plan_type == "complex")
    _PROTECTED = {"outline_feedback", "current_blueprint", "blueprint_history"}
    _plan = state.get("execution_plan") or []
    for _step in _plan:
        if _step.get("tool") == "tool_outline_exam":
            _ov = {k: v for k, v in (_step.get("params_override") or {}).items() if k not in _PROTECTED}
            if _ov:
                exam_config.update(_ov)
                logger.info("execution_plan override applied to outline exam_config: %s for exam %s", list(_ov.keys()), exam_id)
            break

    # ── Blueprint history tracking ───────────────────────────────────────────
    # Keep a running list of all blueprints generated in prior rejection cycles.
    # This gives the outline agent "memory" of what was already tried.
    blueprint_history = list(state.get("blueprint_history") or [])
    current_blueprint = state.get("blueprint", [])

    # G8: Inject rejection feedback into exam_config for re-generation
    rejection_history = state.get("checkpoint_1_rejection_history", [])
    logger.debug("[create_outline] exam_id=%s, rejection_history_len=%d", exam_id, len(rejection_history))
    if rejection_history:
        last_feedback = rejection_history[-1].get("feedback", "")
        if last_feedback:
            exam_config["outline_feedback"] = last_feedback
            # Pass the current blueprint so LLM can modify it (not generate from scratch)
            if current_blueprint:
                exam_config["current_blueprint"] = current_blueprint
                # Append to history BEFORE this new generation round
                blueprint_history.append({
                    "round": len(rejection_history),
                    "feedback": last_feedback,
                    "blueprint": current_blueprint,
                })
            warnings.append("Injecting blueprint rejection feedback for regeneration")
            logger.debug("[create_outline] FEEDBACK INJECTED (from state): %.100s", last_feedback)
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
                    if current_blueprint:
                        exam_config["current_blueprint"] = current_blueprint
                        blueprint_history.append({
                            "round": 1,
                            "feedback": _feedback,
                            "blueprint": current_blueprint,
                        })
                    warnings.append("Injecting blueprint rejection feedback from Redis fallback")
                    logger.debug("[create_outline] FEEDBACK INJECTED (from Redis): %.100s", _feedback)
        except Exception as _e:
            logger.debug("[create_outline] Redis fallback failed: %s", _e)

    # Pass full blueprint history to outline agent so it can avoid repeating mistakes
    if blueprint_history:
        exam_config["blueprint_history"] = blueprint_history

    # Consume coverage_report published by RetrievalAgent (peer-to-peer via message bus)
    try:
        from app.agents.messaging import AgentMessageBus
        from app.core.redis_client import get_redis_client as _get_redis
        bus = AgentMessageBus(_get_redis())
        coverage_messages = await bus.consume(exam_id, recipient="outline", message_types=["coverage_report"])
        if coverage_messages:
            latest = coverage_messages[-1]
            weak_chapters = latest.payload.get("weak_chapters", [])
            if weak_chapters:
                exam_config.setdefault("coverage_hints", {})["weak_chapters"] = weak_chapters
                warnings.append(
                    f"OutlineAgent received coverage_report from RetrievalAgent: "
                    f"weak coverage in {weak_chapters} — adjusting distribution."
                )
                logger.info(
                    "[create_outline] peer message: weak_chapters=%s → reducing question count for those chapters",
                    weak_chapters,
                )
    except Exception as _e:
        logger.debug("coverage_report consume failed (non-critical): %s", _e)

    logger.debug("[create_outline] exam_id=%s, retrieved_context_chunks=%d, calling OutlineAgent...", exam_id, len(retrieved_context))

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
    logger.debug("[create_outline] exam_id=%s, blueprint_slots=%d, distribution=%s", exam_id, len(blueprint), distribution_summary)

    if outline_result.status != AgentStatus.SUCCESS:
        warnings.append(f"Outline creation had issues: {outline_result.status.value}")

    cost_report["outline"] = outline_result.token_usage.model_dump()

    def _slot_type(slot: dict) -> str:
        raw = str(slot.get("type") or "mcq").strip().lower().replace("-", "_").replace(" ", "_")
        if raw in {"essay", "tu_luan", "tự_luận"}:
            return "essay"
        if raw in {"dung_sai", "đúng_sai", "true_false", "tf"}:
            return "dung_sai"
        if raw in {"short_answer", "tra_loi_ngan", "trả_lời_ngắn", "sa"}:
            return "short_answer"
        return "mcq"

    type_counts = {"mcq": 0, "essay": 0, "dung_sai": 0, "short_answer": 0}
    for slot in blueprint:
        type_counts[_slot_type(slot)] += 1

    type_summary = " + ".join(
        label
        for label in (
            f"{type_counts['mcq']} MCQ" if type_counts["mcq"] else "",
            f"{type_counts['essay']} Essay" if type_counts["essay"] else "",
            f"{type_counts['dung_sai']} Đúng-Sai" if type_counts["dung_sai"] else "",
            f"{type_counts['short_answer']} Trả lời ngắn" if type_counts["short_answer"] else "",
        )
        if label
    ) or "0 câu"

    # Emit event via WebSocket
    _emit(state, {
        "type": "outline_created",
        "blueprint_slots": len(blueprint),
        "mcq_count": type_counts["mcq"],
        "essay_count": type_counts["essay"],
        "dung_sai_count": type_counts["dung_sai"],
        "short_answer_count": type_counts["short_answer"],
    })
    # Stream blueprint summary to reasoning feed
    _emit(state, {
        "type": "reasoning_chunk",
        "step_id": "step-2",
        "chunk": f"Hoàn tất! Tạo {len(blueprint)} câu ({type_summary}).\n",
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
        "blueprint_history": blueprint_history,
        "distribution_summary": distribution_summary,
        "cost_report": cost_report,
        "current_agent": AgentRole.OUTLINE,
        "warnings": warnings,
        "updated_at": state.get("updated_at"),
    }

