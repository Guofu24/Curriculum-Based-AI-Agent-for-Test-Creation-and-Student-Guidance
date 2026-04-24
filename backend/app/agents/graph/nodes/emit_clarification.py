"""emit_clarification — Emit clarification questions and stop."""

from app.agents.graph.state import ExamGraphState


async def emit_clarification(state: ExamGraphState) -> ExamGraphState:
    """
    Terminal node when clarification is needed.

    Emits the clarification_needed event via WebSocket and stops.
    The frontend should handle the clarification flow and retry.

    Args:
        state: Contains checkpoint_0_requirements with clarification_questions.

    Returns:
        Updated state (pipeline ends here — this node goes to END).
    """
    questions = state.get("checkpoint_0_requirements", {}).get("clarification_questions", [])

    # Emit via WebSocket (stream_callback is handled externally by the task layer)
    from app.websocket.manager import get_connection_manager
    try:
        manager = get_connection_manager()
        exam_id = state.get("exam_id", "")
        from app.websocket.manager import SSEvent
        # Emit clarification event
        await manager.emit(exam_id, {
            "type": "clarification_needed",
            "data": {"clarification_questions": questions},
        })
    except Exception:
        pass  # Non-blocking

    return {
        **state,
        "pipeline_status": "clarification_needed",  # type: ignore
    }
