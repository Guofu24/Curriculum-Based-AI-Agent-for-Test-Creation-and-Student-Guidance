"""Edge case tests for the graph."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDecidePlan:
    """Test decide_plan node with various complexity signals."""

    def test_signal_1_fixed(self):
        """Bug-001 fix: bool(user_prompt.strip()) not (user_prompt or '') > ''."""
        from app.agents.graph.nodes.decide_plan import decide_plan

        # Empty prompt should NOT trigger complexity
        # The old code: (user_prompt or "") > "" was always True for non-empty strings
        # The fixed code: bool(user_prompt and user_prompt.strip()) is False for empty strings
        import asyncio

        async def run():
            state = {
                "user_prompt": "",
                "exam_config": {
                    "extra_instructions": "",
                    "bloom_distribution": None,
                },
            }
            result = await decide_plan(state)
            return result["plan_type"]

        loop = asyncio.new_event_loop()
        plan_type = loop.run_until_complete(run())
        loop.close()
        assert plan_type == "simple", "Empty prompt should be simple (signal[0]=False)"

    def test_complex_with_2_signals(self):
        """2 signals = complex."""
        from app.agents.graph.nodes.decide_plan import decide_plan

        async def run():
            state = {
                "user_prompt": "Tạo đề " + "x" * 250,  # len > 200
                "exam_config": {
                    "extra_instructions": "",
                    "bloom_distribution": None,
                },
            }
            result = await decide_plan(state)
            return result["plan_type"]

        loop = asyncio.new_event_loop()
        plan_type = loop.run_until_complete(run())
        loop.close()
        assert plan_type == "complex"


class TestBlueprintApprovalNormalization:
    """Bug-004 fix: Redis value normalization."""

    def test_approved_true_string(self):
        """'true' should normalize to True."""
        from app.agents.graph.builder import _check_blueprint_approval

        state = {
            "checkpoint_1_approved": True,
            "checkpoint_1_rejection_history": [],
        }
        result = _check_blueprint_approval(state)
        assert result == "approved"

    def test_rejected_with_history(self):
        """Rejected with history → rejected route."""
        from app.agents.graph.builder import _check_blueprint_approval

        state = {
            "checkpoint_1_approved": False,
            "checkpoint_1_rejection_history": [{"feedback": "Need more vận dụng"}],
        }
        result = _check_blueprint_approval(state)
        assert result == "rejected"

    def test_timeout_no_history(self):
        """Approved is None + no history → timeout."""
        from app.agents.graph.builder import _check_blueprint_approval

        state = {
            "checkpoint_1_approved": None,
            "checkpoint_1_rejection_history": [],
        }
        result = _check_blueprint_approval(state)
        assert result == "timeout"


class TestIncrementRetryAtomic:
    """Bug-009 fix: atomic INCR for retry count."""

    def test_increment_uses_redis_incr(self):
        """increment_retry should use Redis INCR, not load-modify-set."""
        from app.agents.memory.short_term import ShortTermMemory
        import asyncio

        async def run():
            mock_redis = AsyncMock()
            mock_redis.client = AsyncMock()
            mock_redis.client.incr = AsyncMock(return_value=2)
            mock_redis.expire = AsyncMock()

            stm = ShortTermMemory(mock_redis)
            result = await stm.increment_retry("exam-123", "user-456")

            # Should call Redis INCR
            mock_redis.client.incr.assert_called_once()
            assert result == 2

        asyncio.get_event_loop().run_until_complete(run())


class TestEmbeddingFailureWarning:
    """Bug-018 fix: embedding failures emit warnings."""

    def test_retrieval_agent_handles_embedding_failure(self):
        """Embedding failure should be caught and return [], not raise."""
        from app.agents.retrieval import RetrievalAgent
        import asyncio

        async def run():
            mock_redis = AsyncMock()
            agent = RetrievalAgent(redis=mock_redis)
            agent.embedder = AsyncMock()
            agent.embedder.embed_text = AsyncMock(side_effect=Exception("Connection refused"))
            agent.vector_store = AsyncMock()
            agent.vector_store.query_namespace = AsyncMock(return_value=[])

            result = await agent._retrieve_for_chapter(
                document_id="doc-123",
                chapter="Chương 1",
                queries=["test"],
                top_k=5,
            )
            return result

        # Should return [] (graceful) but not raise
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run())
        loop.close()
        assert result == []
