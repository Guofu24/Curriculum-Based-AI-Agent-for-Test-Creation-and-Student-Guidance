"""Tests for validate_questions node — Bug-008 fix verification."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
class TestValidateQuestions:
    """Test validate_questions node."""

    async def test_deduplicates_issues_with_same_question_id_and_type(self, base_state, sample_questions):
        """Bug-008 fix: same question_id + issue_type should appear only once."""
        from app.agents.graph.nodes.validate_questions import validate_questions

        state = {
            **base_state,
            "questions": sample_questions,
            "redis": AsyncMock(),
        }

        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock()
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.value = "retry_needed"
        mock_result.issues = [
            {"question_id": "MCQ_001", "issue_type": "bloom_mismatch", "detail": "From skill"},
            {"question_id": "MCQ_001", "issue_type": "bloom_mismatch", "detail": "From LLM"},  # duplicate!
            {"question_id": "MCQ_002", "issue_type": "scope_violation", "detail": "From skill"},
        ]
        mock_result.token_usage = MagicMock()
        mock_result.token_usage.model_dump = lambda: {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        mock_result.warnings = []
        mock_result.bloom_compliance = {}
        mock_result.scope_violations = []
        mock_validator.validate.return_value = mock_result

        with patch("app.agents.validator.ValidatorAgent", return_value=mock_validator):
            result = await validate_questions(state)

        issues = result["retry_issues"]
        mcq_001_bloom = [
            i for i in issues
            if i["question_id"] == "MCQ_001" and i["issue_type"] == "bloom_mismatch"
        ]
        assert len(mcq_001_bloom) == 1, f"Expected 1 bloom_mismatch for MCQ_001, got {len(mcq_001_bloom)}"

    async def test_keeps_different_issue_types_for_same_question(self, base_state, sample_questions):
        """Different issue_types for the same question_id should both be kept."""
        from app.agents.graph.nodes.validate_questions import validate_questions

        state = {
            **base_state,
            "questions": sample_questions,
            "redis": AsyncMock(),
        }

        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock()
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.value = "retry_needed"
        mock_result.issues = [
            {"question_id": "MCQ_001", "issue_type": "bloom_mismatch", "detail": "Bloom mismatch"},
            {"question_id": "MCQ_001", "issue_type": "scope_violation", "detail": "Scope violation"},  # different type
        ]
        mock_result.token_usage = MagicMock()
        mock_result.token_usage.model_dump = lambda: {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        mock_result.warnings = []
        mock_result.bloom_compliance = {}
        mock_result.scope_violations = []
        mock_validator.validate.return_value = mock_result

        with patch("app.agents.validator.ValidatorAgent", return_value=mock_validator):
            result = await validate_questions(state)

        issues = result["retry_issues"]
        assert len(issues) == 2  # Both different issue_types should be kept

    async def test_emits_validation_result_event(self, base_state, sample_questions):
        """WebSocket event should be emitted after validation."""
        from app.agents.graph.nodes.validate_questions import validate_questions

        state = {
            **base_state,
            "questions": sample_questions,
            "redis": AsyncMock(),
        }

        mock_validator = MagicMock()
        mock_validator.validate = AsyncMock()
        mock_result = MagicMock()
        mock_result.status = MagicMock()
        mock_result.status.value = "success"
        mock_result.issues = []
        mock_result.token_usage = MagicMock()
        mock_result.token_usage.model_dump = lambda: {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        mock_result.warnings = []
        mock_result.bloom_compliance = {}
        mock_result.scope_violations = []
        mock_validator.validate.return_value = mock_result

        with patch("app.agents.validator.ValidatorAgent", return_value=mock_validator):
            with patch("app.agents.graph.nodes.validate_questions._emit") as mock_emit:
                result = await validate_questions(state)
                assert mock_emit.called
