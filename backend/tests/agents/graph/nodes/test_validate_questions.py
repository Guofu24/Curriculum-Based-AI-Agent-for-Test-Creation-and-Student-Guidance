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


def test_chapter_aliases_accept_canonical_scope_with_display_title():
    from app.agents.validator import (
        _build_allowed_chapter_aliases,
        _chapter_in_scope,
    )

    exam_config = {
        "scope": ["ch1"],
        "scope_units": [
            {
                "chapter_id": "ch1",
                "chapter_title": "A. QUANG HÌNH HỌC",
                "section_id": "ch1_sec1",
                "section_title": "Bản mặt song song",
                "scope_unit_key": "ch1_sec1",
            }
        ],
    }

    aliases = _build_allowed_chapter_aliases(exam_config, primary_chunks=[])

    assert _chapter_in_scope("A. QUANG HÌNH HỌC", aliases)
    assert not _chapter_in_scope("B. GIAO THOA ĐỊNH XỨ", aliases)


def test_chapter_aliases_ignore_punctuation_spacing():
    from app.agents.validator import (
        _build_allowed_chapter_aliases,
        _chapter_in_scope,
    )

    aliases = _build_allowed_chapter_aliases(
        {"scope": ["A.QUANG HÌNH HỌC"]},
        primary_chunks=[],
    )

    assert _chapter_in_scope("A. QUANG HÌNH HỌC", aliases)


@pytest.mark.asyncio
async def test_validator_does_not_scope_fail_title_for_selected_chapter():
    from app.agents.validator import ValidatorAgent

    class FakeLLM:
        async def chat(self, **kwargs):
            return """
            {
              "validation_passed": true,
              "questions": [
                {
                  "question_id": "MCQ_001",
                  "answer_correct": true,
                  "model_answer": "C",
                  "bloom_compliant": true,
                  "bloom_actual": "nhan_biet",
                  "bloom_confidence": 0.9,
                  "scope_ok": true,
                  "scope_violation_detail": null,
                  "issues": []
                }
              ],
              "bloom_compliance_summary": {},
              "scope_violations": [],
              "approved_for_publish": true
            }
            """

    validator = ValidatorAgent(redis=None)
    validator.llm = FakeLLM()

    result = await validator.validate(
        questions=[
            {
                "question_id": "MCQ_001",
                "type": "mcq",
                "chapter": "A. QUANG HÌNH HỌC",
                "bloom_level": "nhan_biet",
                "stem": "Theo định nghĩa trong quang hình học, bản mặt song song được giới hạn bởi điều kiện nào?",
                "options": {
                    "A": "Hai mặt phẳng cắt nhau.",
                    "B": "Một mặt phẳng và một mặt cầu.",
                    "C": "Hai mặt phẳng song song với nhau.",
                    "D": "Hai mặt cầu đồng tâm.",
                },
                "correct_answer": "C",
            }
        ],
        exam_config={
            "scope": ["ch1"],
            "scope_units": [
                {
                    "chapter_id": "ch1",
                    "chapter_title": "A. QUANG HÌNH HỌC",
                    "section_id": "ch1_sec1",
                    "section_title": "Bản mặt song song",
                    "scope_unit_key": "ch1_sec1",
                }
            ],
        },
        retrieved_context=[
            {
                "chunk_id": "chunk_ch1_0001",
                "chapter_id": "ch1",
                "chapter": "A. QUANG HÌNH HỌC",
                "content": "Bản mặt song song là khối chất trong suốt giới hạn bởi hai mặt phẳng song song.",
                "role": "primary",
            }
        ],
        trace_id="test-validator-scope",
    )

    assert result.validation_passed
    assert all(issue.get("issue_type") != "scope_violation" for issue in result.issues)
