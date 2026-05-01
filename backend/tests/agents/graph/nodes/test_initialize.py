"""Tests for the initialize node."""

import pytest
import time
from app.agents.graph.nodes.initialize import initialize
from app.agents.graph.state import PipelineStatus, HITLCheckpointStatus


@pytest.mark.asyncio
class TestInitialize:
    """Test initialize node sets all required defaults."""

    async def test_sets_pipeline_status_to_running(self, base_state):
        """Pipeline should start in RUNNING status."""
        result = await initialize(base_state)
        assert result["pipeline_status"] == PipelineStatus.RUNNING

    async def test_copies_exam_config_original(self, base_state):
        """exam_config_original should be a deep copy, not a reference."""
        result = await initialize(base_state)
        assert isinstance(result["exam_config_original"], dict)
        assert result["exam_config_original"] == base_state["exam_config"]

    async def test_merges_user_prompt_into_exam_config(self, base_state):
        """user_prompt from top-level should be available."""
        result = await initialize(base_state)
        assert result["user_prompt"] == "Tạo đề kiểm tra Vật lý lớp 10"

    async def test_initializes_all_checkpoint_statuses_to_pending(self, base_state):
        """All HITL checkpoints should start as PENDING."""
        result = await initialize(base_state)
        assert result["checkpoint_0_status"] == HITLCheckpointStatus.PENDING
        assert result["checkpoint_1_status"] == HITLCheckpointStatus.PENDING
        assert result["checkpoint_2_status"] == HITLCheckpointStatus.PENDING
        assert result["checkpoint_3_status"] == HITLCheckpointStatus.PENDING

    async def test_initializes_retry_count_to_zero(self, base_state):
        """Retry count should start at 0."""
        result = await initialize(base_state)
        assert result["retry_count"] == 0
        assert result["retry_issues"] == []

    async def test_sets_checkpoint_timeouts(self, base_state):
        """HITL checkpoints should have timeout timestamps set."""
        result = await initialize(base_state)
        now = time.time()
        # Checkpoint 1: 30 min timeout
        assert 1795 <= result["checkpoint_1_timeout_at"] - now <= 1805
        # Checkpoint 2: 60 min timeout
        assert 3595 <= result["checkpoint_2_timeout_at"] - now <= 3605

    async def test_initializes_empty_lists_for_context(self, base_state):
        """Memory/context fields should be empty lists."""
        result = await initialize(base_state)
        assert result["retrieved_context"] == []
        assert result["allowed_concepts"] == []
        assert result["topics_used"] == []

    async def test_copies_scope_from_exam_config(self, base_state):
        """scope should be extracted from exam_config."""
        result = await initialize(base_state)
        assert result["scope"] == ["Chương 1", "Chương 2"]

    async def test_handles_missing_document_id(self, base_state):
        """document_id=None should be handled gracefully."""
        state = {**base_state, "document_id": None}
        result = await initialize(state)
        assert result["document_id"] is None

    async def test_scope_comes_from_exam_config(self, base_state):
        """Scope should be extracted from exam_config (not top-level state)."""
        result = await initialize(base_state)
        assert result["scope"] == ["Chương 1", "Chương 2"]
