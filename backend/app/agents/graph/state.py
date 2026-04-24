"""
LangGraph StateGraph for the Exam Generation pipeline.

ExamGraphState is the central state passed between nodes.
Each node reads from this state and returns updates.
"""

from typing import TypedDict, Literal
from enum import Enum


class PipelineStatus(str, Enum):
    """Pipeline execution status."""
    CLARIFICATION_NEEDED = "clarification_needed"
    RUNNING = "running"
    PAUSED_AT_CHECKPOINT_1 = "paused_checkpoint_1"
    RETRY_LOOP = "retry_loop"
    COMPLETED = "completed"
    FAILED = "failed"


class HITLCheckpointStatus(str, Enum):
    """HITL checkpoint approval status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class AgentRole(str, Enum):
    """Currently executing agent role."""
    ORCHESTRATOR = "orchestrator"
    RETRIEVAL = "retrieval"
    OUTLINE = "outline"
    BUILDER = "builder"
    VALIDATOR = "validator"
    PLANNER = "planner"


class ExamGraphState(TypedDict, total=False):
    """
    Complete state for the LangGraph exam generation pipeline.

    All fields are optional (TypedDict total=False) so that nodes can
    incrementally populate fields. Every field has a default at the
    ``initialize`` node so the graph always starts with a well-defined state.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    exam_id: str
    user_id: str
    document_id: str | None

    # ── Config snapshot ───────────────────────────────────────────────────
    exam_config: dict
    exam_config_original: dict
    user_prompt: str | None
    extra_instructions: str | None
    scope: list[str]

    # ── Pipeline execution state ─────────────────────────────────────────
    pipeline_status: PipelineStatus
    current_agent: AgentRole | None
    current_step: int
    total_steps: int

    # ── Intermediate products from agents ────────────────────────────────
    teacher_prefs: dict | None
    plan_type: str  # "complex" | "simple"
    execution_plan: list[dict]

    retrieval_result: dict | None  # {"status", "retrieved_chunks", "coverage_map", ...}
    outline_result: dict | None  # {"status", "blueprint", "distribution_summary", ...}
    blueprint: list[dict] | None
    distribution_summary: dict | None
    builder_result: dict | None  # {"status", "questions", "topics_used", ...}
    validation_result: dict | None  # {"status", "validation_passed", "issues", ...}
    questions: list[dict]
    approved_questions: list[dict]
    cost_report: dict

    # ── HITL Checkpoint states ───────────────────────────────────────────
    checkpoint_0_status: HITLCheckpointStatus
    checkpoint_0_requirements: dict | None

    checkpoint_1_status: HITLCheckpointStatus
    checkpoint_1_approved: bool | None
    checkpoint_1_rejection_history: list[dict]
    checkpoint_1_timeout_at: float | None

    checkpoint_2_status: HITLCheckpointStatus
    checkpoint_2_approved: bool | None
    checkpoint_2_feedback: str | None
    checkpoint_2_timeout_at: float | None

    checkpoint_3_status: HITLCheckpointStatus

    # ── Retry state (G9) ─────────────────────────────────────────────────
    retry_count: int
    retry_issues: list[dict]
    topics_used: list[str]

    # ── Memory / context ─────────────────────────────────────────────────
    retrieved_context: list[dict]  # retrieved chunks
    allowed_concepts: list[str]  # for ScopeGuard
    allowed_chapters: list[str]
    conversation_history: list[dict]
    review_approved: bool

    # ── Errors and warnings ───────────────────────────────────────────────
    warnings: list[str]
    error: str | None
    critical_error: str | None

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: float
    updated_at: float
