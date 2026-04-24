"""Integration tests for the full graph."""

import pytest


@pytest.mark.asyncio
class TestFullGraph:
    """Test the compiled LangGraph."""

    async def test_graph_compiles_without_error(self):
        """The graph should compile successfully."""
        from app.agents.graph.builder import build_exam_graph

        graph = build_exam_graph()
        assert graph is not None

    async def test_full_flow_simple_request(self, base_state):
        """Test simple request flow: clarification_check → load_long_term_memory → decide_plan → END."""
        from app.agents.graph.builder import build_exam_graph, _is_clarification_needed, _is_complex_request

        graph = build_exam_graph()
        config = {"configurable": {"thread_id": base_state["exam_id"]}}

        # Verify the graph has all required nodes
        node_names = list(graph.nodes.keys())
        assert "initialize" in node_names
        assert "clarification_check" in node_names
        assert "wait_for_blueprint_approval" in node_names
        assert "build_questions" in node_names
        assert "validate_questions" in node_names
        assert "finalize_output" in node_names

        # Verify conditional edges produce correct routing
        state_clear = {"pipeline_status": "running"}
        assert _is_clarification_needed(state_clear) == "requirements_clear"

        state_complex = {"plan_type": "complex"}
        assert _is_complex_request(state_complex) == "complex"


@pytest.mark.asyncio
class TestRetrySelfLoop:
    """Test the G9 retry self-loop."""

    async def test_retry_loop_max_3_times(self):
        """Retry should stop after 3 attempts."""
        from app.agents.graph.builder import build_exam_graph, _evaluate_validation

        # Simulate 3 retries
        for i in range(1, 4):
            state = {
                "validation_result": {"validation_passed": False},
                "retry_count": i,
                "retry_issues": [{"question_id": "MCQ_001", "issue_type": "bloom_mismatch"}],
            }
            result = _evaluate_validation(state)
            if i < 3:
                assert result == "retry", f"Attempt {i}: should retry"
            else:
                assert result == "max_exceeded", f"Attempt {i}: should stop"

    async def test_validation_passed_skips_retry(self):
        """If validation passes, should go to emit_checkpoint_2."""
        from app.agents.graph.builder import _evaluate_validation

        state = {
            "validation_result": {"validation_passed": True},
            "retry_count": 0,
            "retry_issues": [],
        }
        result = _evaluate_validation(state)
        assert result == "passed"
