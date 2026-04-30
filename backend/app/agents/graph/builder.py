"""
LangGraph StateGraph builder for the exam generation pipeline.

Compile this graph and use it in the OrchestratorAgent.
The graph is built lazily (compiled once) and reused across invocations.
"""

import logging

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph.state import ExamGraphState
from app.agents.graph.nodes import ALL_NODES

logger = logging.getLogger("app.agents.graph")

# Shared checkpointer: all graph instances share the same memory.
# This allows resume_from_state() to work across different agent instances.
_shared_checkpointer = MemorySaver()


def get_shared_checkpointer() -> MemorySaver:
    """Return the shared checkpointer for all graph instances."""
    return _shared_checkpointer


# ── Conditional edge routing functions ──────────────────────────────────────────


def _is_clarification_needed(state: ExamGraphState) -> str:
    """Route after clarification_check."""
    from app.agents.graph.state import PipelineStatus
    if state.get("pipeline_status") == PipelineStatus.CLARIFICATION_NEEDED:
        return "clarification_needed"
    return "requirements_clear"


def _is_complex_request(state: ExamGraphState) -> str:
    """Route after decide_plan."""
    return state.get("plan_type", "simple")


def _check_retrieval_status(state: ExamGraphState) -> str:
    """Route after retrieve_knowledge."""
    result = state.get("retrieval_result", {})
    status = result.get("status", "failed")
    if status in ("success", "partial"):
        return "success"
    return "failed"


def _check_outline_status(state: ExamGraphState) -> str:
    """Route after create_outline."""
    result = state.get("outline_result", {})
    status = result.get("status", "failed")
    if status in ("success", "partial"):
        return "success"
    return "failed"


def _check_blueprint_approval(state: ExamGraphState) -> str:
    """
    Route after wait_for_blueprint_approval interrupt.

    - PENDING → "waiting" (graph stays alive, polls for approval externally)
    - approved=True → build_questions
    - approved=False + rejection_history → create_outline (G8: regenerate outline)
    - approved=False + no history → handle_timeout
    """
    from app.agents.graph.state import HITLCheckpointStatus
    status = state.get("checkpoint_1_status")

    if status == HITLCheckpointStatus.PENDING:
        return "waiting"
    approved = state.get("checkpoint_1_approved")
    rejection_history = state.get("checkpoint_1_rejection_history", [])

    if approved is True:
        return "approved"
    if approved is False:
        if rejection_history:
            return "rejected"
        return "timeout"
    return "timeout"


def _check_builder_status(state: ExamGraphState) -> str:
    """Route after build_questions."""
    result = state.get("builder_result", {})
    status = result.get("status", "failed")
    if status in ("success", "partial"):
        return "success"
    return "failed"


def _evaluate_validation(state: ExamGraphState) -> str:
    """
    G9: Route after check_validation_result.

    - validation_passed → emit_checkpoint_2
    - needs_retry AND retry_count < 3 → retry_builder (self-loop)
    - max_exceeded → handle_max_retries_exceeded
    """
    validation_result = state.get("validation_result", {})
    validation_passed = validation_result.get("validation_passed", False)
    retry_count = int(state.get("retry_count", 0))
    max_retries = 3
    issues = state.get("retry_issues", [])

    if validation_passed:
        return "passed"
    if retry_count < max_retries and len(issues) > 0:
        return "retry"
    return "max_exceeded"


def _check_review_approval(state: ExamGraphState) -> str:
    """Route after wait_for_review interrupt."""
    approved = state.get("checkpoint_2_approved")

    if approved is True:
        return "approved"
    if approved is False:
        return "rejected"
    return "timeout"


# ── Graph builder ──────────────────────────────────────────────────────────────


def build_exam_graph(checkpointer=None):
    """
    Build and compile the exam generation StateGraph.

    Args:
        checkpointer: LangGraph checkpointer (e.g. MemorySaver for dev,
                      PostgresSaver for production). Defaults to the shared checkpointer
                      so all instances share state (enabling resume from HTTP).

    Returns:
        Compiled StateGraph ready for ainvoke() calls.
    """
    workflow = StateGraph(ExamGraphState)

    # Add all nodes
    for node_name, node_func in ALL_NODES:
        workflow.add_node(node_name, node_func)

    # ── Fixed edges (no conditions) ───────────────────────────────────────

    workflow.add_edge(START, "initialize")
    workflow.add_edge("initialize", "clarification_check")
    workflow.add_edge("load_long_term_memory", "decide_plan")
    workflow.add_edge("plan_complex", "retrieve_knowledge")
    workflow.add_edge("handle_retrieval_failure", "create_outline")
    workflow.add_edge("emit_checkpoint_1", "wait_for_blueprint_approval")
    workflow.add_edge("handle_outline_failure", END)
    workflow.add_edge("handle_builder_failure", "emit_checkpoint_2")
    workflow.add_edge("handle_max_retries_exceeded", "emit_checkpoint_2")
    workflow.add_edge("retry_builder", "build_questions")  # self-loop: rebuild → then validate
    workflow.add_edge("emit_checkpoint_2", "wait_for_review")
    workflow.add_edge("save_teacher_preferences", "emit_checkpoint_3")
    workflow.add_edge("finalize_with_feedback", END)
    workflow.add_edge("emit_checkpoint_3", "finalize_output")
    workflow.add_edge("finalize_output", END)
    workflow.add_edge("handle_timeout", END)
    workflow.add_edge("emit_clarification", END)

    # ── Conditional edges ─────────────────────────────────────────────────

    # Clarification routing
    workflow.add_conditional_edges(
        "clarification_check",
        _is_clarification_needed,
        {
            "clarification_needed": "emit_clarification",
            "requirements_clear": "load_long_term_memory",
        }
    )

    # Complexity routing
    workflow.add_conditional_edges(
        "decide_plan",
        _is_complex_request,
        {
            "complex": "plan_complex",
            "simple": "retrieve_knowledge",
        }
    )

    # Retrieval → Outline
    workflow.add_conditional_edges(
        "retrieve_knowledge",
        _check_retrieval_status,
        {
            "success": "create_outline",
            "failed": "handle_retrieval_failure",
        }
    )

    # Outline → HITL Checkpoint 1
    workflow.add_conditional_edges(
        "create_outline",
        _check_outline_status,
        {
            "success": "emit_checkpoint_1",
            "failed": "handle_outline_failure",
        }
    )

    # HITL Checkpoint 1: blueprint approval routing
    workflow.add_conditional_edges(
        "wait_for_blueprint_approval",
        _check_blueprint_approval,
        {
            "approved": "build_questions",
            "rejected": "create_outline",  # G8: regenerate outline with feedback
            "timeout": "handle_timeout",
            "waiting": END,  # Graph ends here — caller polls externally and resumes
        }
    )

    # Build → Validate
    workflow.add_conditional_edges(
        "build_questions",
        _check_builder_status,
        {
            "success": "validate_questions",
            "failed": "handle_builder_failure",
        }
    )

    # Validate → routing node
    workflow.add_edge("validate_questions", "check_validation_result")

    # Retry loop: G9 conditional self-loop
    workflow.add_conditional_edges(
        "check_validation_result",
        _evaluate_validation,
        {
            "passed": "emit_checkpoint_2",
            "retry": "retry_builder",  # self-loop: back to validate_questions
            "max_exceeded": "handle_max_retries_exceeded",
        }
    )

    # HITL Checkpoint 2: review approval routing
    workflow.add_conditional_edges(
        "wait_for_review",
        _check_review_approval,
        {
            "approved": "save_teacher_preferences",
            "rejected": "finalize_with_feedback",
            "timeout": "handle_timeout",
        }
    )

    # Compile with checkpointer
    checkpointer = checkpointer or _shared_checkpointer
    return workflow.compile(checkpointer=checkpointer)
