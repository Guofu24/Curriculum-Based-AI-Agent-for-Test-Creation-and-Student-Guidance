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

# Lazy checkpointer — initialized at app startup via init_shared_checkpointer().
# Falls back to MemorySaver if langgraph-checkpoint-postgres is not installed or
# PostgreSQL is unavailable.  MemorySaver loses state on restart, which breaks HITL
# checkpoint resume — always prefer the Postgres-backed checkpointer in production.
_shared_checkpointer = None
_shared_pg_conn = None  # psycopg AsyncConnection — closed at app shutdown


def get_shared_checkpointer():
    """Return the active checkpointer (AsyncPostgresSaver or MemorySaver fallback)."""
    global _shared_checkpointer
    if _shared_checkpointer is None:
        logger.warning(
            "LangGraph checkpointer not initialized — using MemorySaver (state lost on "
            "restart). Call init_shared_checkpointer() at app startup."
        )
        _shared_checkpointer = MemorySaver()
    return _shared_checkpointer


async def init_shared_checkpointer() -> None:
    """
    Initialize the shared LangGraph checkpointer with PostgreSQL persistence.

    Must be called once during application startup (FastAPI lifespan).
    Falls back to MemorySaver when:
      - langgraph-checkpoint-postgres / psycopg not installed
      - PostgreSQL is unreachable

    Postgres-backed checkpointer survives server restarts, enabling HITL
    checkpoint resume across Celery worker restarts and process bounces.
    Creates the required checkpoint tables via checkpointer.setup() on first run.
    """
    global _shared_checkpointer, _shared_pg_conn
    if _shared_checkpointer is not None:
        return  # Already initialized

    try:
        import psycopg  # type: ignore
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore
        from app.core.config import get_settings

        settings = get_settings()
        # DATABASE_URL uses the asyncpg driver prefix (for SQLAlchemy).
        # psycopg3 expects a plain postgresql:// URL.
        pg_url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

        conn = await psycopg.AsyncConnection.connect(pg_url, autocommit=True)
        checkpointer = AsyncPostgresSaver(conn)
        await checkpointer.setup()  # Creates checkpoint tables if they don't exist
        _shared_checkpointer = checkpointer
        _shared_pg_conn = conn
        logger.info("LangGraph checkpointer: AsyncPostgresSaver (PostgreSQL) ✓")

    except ImportError:
        logger.warning(
            "langgraph-checkpoint-postgres or psycopg not installed — "
            "install with: pip install langgraph-checkpoint-postgres 'psycopg[binary]'. "
            "Falling back to MemorySaver (HITL state lost on restart)."
        )
        _shared_checkpointer = MemorySaver()

    except Exception as exc:
        logger.warning(
            "AsyncPostgresSaver init failed (%s) — falling back to MemorySaver.", exc
        )
        _shared_checkpointer = MemorySaver()


def get_checkpointer_type() -> str:
    """Return the active checkpointer class name for health-check logging."""
    if _shared_checkpointer is None:
        return "uninitialized"
    return type(_shared_checkpointer).__name__


async def close_shared_checkpointer() -> None:
    """
    Close the PostgreSQL connection used by the checkpointer.
    Must be called at application shutdown (FastAPI lifespan teardown).
    """
    global _shared_pg_conn
    if _shared_pg_conn is not None:
        try:
            await _shared_pg_conn.close()
            logger.info("LangGraph checkpointer connection closed.")
        except Exception as exc:
            logger.debug("Error closing checkpointer connection: %s", exc)
        _shared_pg_conn = None





# ── Conditional edge routing functions ──────────────────────────────────────────


def _is_clarification_needed(state: ExamGraphState) -> str:
    """Route after clarification_check."""
    from app.agents.graph.state import PipelineStatus
    if state.get("pipeline_status") == PipelineStatus.CLARIFICATION_NEEDED:
        return "clarification_needed"
    return "requirements_clear"


def _is_complex_request(state: ExamGraphState) -> str:
    """Route after decide_plan.

    Returns "complex" to fan-out to BOTH plan_complex and retrieve_knowledge in parallel,
    or "simple" to go directly to retrieve_knowledge.
    """
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
    # Fix 1: fanout_complex is a passthrough with two outgoing edges — LangGraph runs both in parallel
    workflow.add_edge("fanout_complex", "plan_complex")
    workflow.add_edge("fanout_complex", "retrieve_knowledge")
    # Both parallel branches converge at merge_plan_retrieval
    workflow.add_edge("plan_complex", "merge_plan_retrieval")
    # simple path: retrieve_knowledge → merge_plan_retrieval (via conditional edge above)
    workflow.add_edge("merge_plan_retrieval", "dispatch_tasks")
    # Fix 3: dispatch_tasks runs focused_retrieval if enqueued, then continues to create_outline
    workflow.add_edge("dispatch_tasks", "create_outline")
    workflow.add_edge("handle_retrieval_failure", "create_outline")
    workflow.add_edge("emit_checkpoint_1", "wait_for_blueprint_approval")
    workflow.add_edge("handle_outline_failure", END)
    workflow.add_edge("handle_builder_failure", "emit_checkpoint_2")
    workflow.add_edge("handle_max_retries_exceeded", "emit_checkpoint_2")
    workflow.add_edge("retry_builder", "build_questions") 
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

    # Fix 1: Complexity routing
    # complex → fanout_complex (passthrough) → plan_complex AND retrieve_knowledge run in parallel
    # simple → retrieve_knowledge directly (skips fanout and planner)
    workflow.add_conditional_edges(
        "decide_plan",
        _is_complex_request,
        {
            "complex": "fanout_complex",
            "simple": "retrieve_knowledge",
        }
    )

    # Retrieval status routing (both simple and complex paths flow through here)
    workflow.add_conditional_edges(
        "retrieve_knowledge",
        _check_retrieval_status,
        {
            "success": "merge_plan_retrieval",
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
