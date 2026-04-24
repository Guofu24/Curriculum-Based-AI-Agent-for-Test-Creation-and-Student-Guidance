"""initialize — Set up the initial ExamGraphState."""

import time
import logging

from app.agents.graph.state import ExamGraphState, HITLCheckpointStatus, PipelineStatus

logger = logging.getLogger("app.agents.graph")


async def initialize(state: ExamGraphState) -> ExamGraphState:
    """
    Entry node: initialize the complete ExamGraphState.

    Called once at the start of every pipeline run. Sets all defaults so
    subsequent nodes never receive undefined fields.

    Args:
        state: Must contain at minimum exam_id, user_id, exam_config.

    Returns:
        Updated ExamGraphState with all fields initialized.
    """
    exam_config = state.get("exam_config") or {}
    scope = list(exam_config.get("scope", []))
    doc_id = state.get("document_id") or exam_config.get("document_id", "") or None
    user_prompt = state.get("user_prompt") or exam_config.get("user_prompt", "") or None
    extra_instructions = state.get("extra_instructions") or exam_config.get("extra_instructions", "") or None

    current_time = time.time()

    # Deep-copy exam_config_original so subsequent modifications don't affect it
    exam_config_original = dict(exam_config)

    return {
        **state,
        "document_id": doc_id if doc_id else None,
        "exam_config_original": exam_config_original,
        "user_prompt": user_prompt,
        "extra_instructions": extra_instructions,
        "scope": scope,
        "pipeline_status": PipelineStatus.RUNNING,
        "current_agent": None,
        "current_step": 0,
        "total_steps": 5,
        # Intermediate products
        "teacher_prefs": None,
        "plan_type": "simple",
        "execution_plan": [],
        "retrieval_result": None,
        "outline_result": None,
        "blueprint": [],
        "distribution_summary": {},
        "builder_result": None,
        "validation_result": None,
        "questions": [],
        "approved_questions": [],
        "cost_report": {},
        # HITL Checkpoints
        "checkpoint_0_status": HITLCheckpointStatus.PENDING,
        "checkpoint_0_requirements": None,
        "checkpoint_1_status": HITLCheckpointStatus.PENDING,
        "checkpoint_1_approved": None,
        "checkpoint_1_rejection_history": [],
        "checkpoint_1_timeout_at": current_time + 1800,  # 30 min
        "checkpoint_2_status": HITLCheckpointStatus.PENDING,
        "checkpoint_2_approved": None,
        "checkpoint_2_feedback": None,
        "checkpoint_2_timeout_at": current_time + 3600,  # 60 min
        "checkpoint_3_status": HITLCheckpointStatus.PENDING,
        # Retry
        "retry_count": 0,
        "retry_issues": [],
        "topics_used": [],
        # Memory
        "retrieved_context": [],
        "allowed_concepts": [],
        "allowed_chapters": list(scope),
        "conversation_history": [],
        "review_approved": False,
        # Errors
        "warnings": [],
        "error": None,
        "critical_error": None,
        # Timestamps
        "created_at": current_time,
        "updated_at": current_time,
    }
