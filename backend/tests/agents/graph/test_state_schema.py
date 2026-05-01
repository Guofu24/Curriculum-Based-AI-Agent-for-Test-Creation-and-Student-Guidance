"""Tests for ExamGraphState schema."""

import pytest
from app.agents.graph.state import (
    ExamGraphState,
    PipelineStatus,
    HITLCheckpointStatus,
    AgentRole,
)


class TestExamGraphState:
    """Test ExamGraphState TypedDict."""

    def test_empty_state_allowed(self):
        """TypedDict total=False allows empty dict."""
        state: ExamGraphState = {}
        assert isinstance(state, dict)

    def test_all_fields_optional(self):
        """Every field can be None or omitted."""
        state: ExamGraphState = {
            "exam_id": "exam-123",
            "user_id": "user-456",
        }
        assert state["exam_id"] == "exam-123"

    def test_pipeline_status_enum(self):
        """PipelineStatus enum values are valid."""
        assert PipelineStatus.RUNNING.value == "running"
        assert PipelineStatus.CLARIFICATION_NEEDED.value == "clarification_needed"
        assert PipelineStatus.COMPLETED.value == "completed"
        assert PipelineStatus.FAILED.value == "failed"

    def test_hitl_status_enum(self):
        """HITLCheckpointStatus enum values are valid."""
        assert HITLCheckpointStatus.PENDING.value == "pending"
        assert HITLCheckpointStatus.APPROVED.value == "approved"
        assert HITLCheckpointStatus.REJECTED.value == "rejected"

    def test_agent_role_enum(self):
        """AgentRole enum values are valid."""
        assert AgentRole.ORCHESTRATOR.value == "orchestrator"
        assert AgentRole.RETRIEVAL.value == "retrieval"
        assert AgentRole.BUILDER.value == "builder"
        assert AgentRole.VALIDATOR.value == "validator"


class TestConditionalEdgeFunctions:
    """Test conditional edge routing functions."""

    def test_is_complex_with_all_signals(self):
        """Complex request: >=2 signals triggers complex routing."""
        from app.agents.graph.builder import _is_complex_request

        state = {
            "plan_type": "complex",
        }
        result = _is_complex_request(state)
        assert result == "complex"

    def test_is_complex_simple(self):
        """Simple request: <2 signals triggers simple routing."""
        from app.agents.graph.builder import _is_complex_request

        state = {
            "plan_type": "simple",
        }
        result = _is_complex_request(state)
        assert result == "simple"

    def test_evaluate_validation_passed(self):
        """Validation passed → emit_checkpoint_2."""
        from app.agents.graph.builder import _evaluate_validation

        state = {
            "validation_result": {"validation_passed": True},
            "retry_count": 0,
            "retry_issues": [],
        }
        result = _evaluate_validation(state)
        assert result == "passed"

    def test_evaluate_validation_retry(self):
        """Validation failed + retries left → retry."""
        from app.agents.graph.builder import _evaluate_validation

        state = {
            "validation_result": {"validation_passed": False},
            "retry_count": 1,
            "retry_issues": [{"question_id": "MCQ_001", "issue_type": "bloom_mismatch"}],
        }
        result = _evaluate_validation(state)
        assert result == "retry"

    def test_evaluate_validation_max_exceeded(self):
        """Validation failed + no retries left → max_exceeded."""
        from app.agents.graph.builder import _evaluate_validation

        state = {
            "validation_result": {"validation_passed": False},
            "retry_count": 3,
            "retry_issues": [{"question_id": "MCQ_001", "issue_type": "bloom_mismatch"}],
        }
        result = _evaluate_validation(state)
        assert result == "max_exceeded"

    def test_evaluate_validation_no_issues_stops_retry(self):
        """Validation failed but no issues → max_exceeded (no retry possible)."""
        from app.agents.graph.builder import _evaluate_validation

        state = {
            "validation_result": {"validation_passed": False},
            "retry_count": 0,
            "retry_issues": [],
        }
        result = _evaluate_validation(state)
        assert result == "max_exceeded"

    def test_check_blueprint_approval_approved(self):
        """Approved → build_questions."""
        from app.agents.graph.builder import _check_blueprint_approval

        state = {
            "checkpoint_1_approved": True,
            "checkpoint_1_rejection_history": [],
        }
        result = _check_blueprint_approval(state)
        assert result == "approved"

    def test_check_blueprint_approval_rejected(self):
        """Rejected with history → create_outline (G8)."""
        from app.agents.graph.builder import _check_blueprint_approval

        state = {
            "checkpoint_1_approved": False,
            "checkpoint_1_rejection_history": [{"feedback": "Need more questions"}],
        }
        result = _check_blueprint_approval(state)
        assert result == "rejected"

    def test_check_blueprint_approval_timeout(self):
        """No approval and no history → timeout."""
        from app.agents.graph.builder import _check_blueprint_approval

        state = {
            "checkpoint_1_approved": None,
            "checkpoint_1_rejection_history": [],
        }
        result = _check_blueprint_approval(state)
        assert result == "timeout"

    def test_check_review_approval_approved(self):
        """Review approved → save_teacher_preferences."""
        from app.agents.graph.builder import _check_review_approval

        state = {"checkpoint_2_approved": True}
        result = _check_review_approval(state)
        assert result == "approved"

    def test_check_review_approval_rejected(self):
        """Review rejected → finalize_with_feedback."""
        from app.agents.graph.builder import _check_review_approval

        state = {"checkpoint_2_approved": False}
        result = _check_review_approval(state)
        assert result == "rejected"
