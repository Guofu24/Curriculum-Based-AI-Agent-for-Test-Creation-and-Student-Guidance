"""finalize_output — Final node: emit completed event and prepare return value."""

import logging
import time

from app.agents.graph.state import ExamGraphState, PipelineStatus
from app.agents.graph.nodes._emit import _emit_async

logger = logging.getLogger("app.agents.graph")


async def finalize_output(state: ExamGraphState) -> ExamGraphState:
    """
    Final node: finalize the pipeline output.

    Calculates total tokens, cost, and comprehensive telemetry metrics,
    then emits the completed event.

    Telemetry captures:
    - Per-stage timing (retrieval_ms, outline_ms, build_ms, validate_ms)
    - LLM call counts
    - Token usage
    - Cache hits
    """
    from app.websocket.manager import get_connection_manager

    questions = state.get("questions", [])
    distribution_summary = state.get("distribution_summary", {})
    cost_report = dict(state.get("cost_report", {}))
    warnings = list(state.get("warnings", []))
    validation_passed = state.get("validation_result", {}).get("validation_passed", False)
    exam_id = state.get("exam_id", "")
    generation_metadata = dict(state.get("generation_metadata", {}))

    # ── Compute per-stage timing from cost_report ──────────────────────
    def extract_ms(cost_entry: dict) -> int:
        """Extract timing from a cost_report entry."""
        return cost_entry.get("execution_time_ms", 0) or 0

    retrieval_ms = extract_ms(cost_report.get("retrieval", {}))
    outline_ms = extract_ms(cost_report.get("outline", {}))
    builder_ms = extract_ms(cost_report.get("builder", {}))
    validator_ms = extract_ms(cost_report.get("validator", {}))
    total_ms = retrieval_ms + outline_ms + builder_ms + validator_ms

    # ── Compute token usage ─────────────────────────────────────────────
    total_tokens = sum(
        cost_report.get(k, {}).get("total_tokens", 0) or 0
        for k in ["retrieval", "outline", "builder", "validator"]
    )
    total_cost = sum(
        cost_report.get(k, {}).get("estimated_cost_usd", 0) or 0
        for k in ["retrieval", "outline", "builder", "validator"]
    )
    cost_report["total_tokens"] = total_tokens
    cost_report["total_cost_usd"] = round(total_cost, 6)

    # ── Compute LLM call count estimate ────────────────────────────────
    # Based on: 1 call for retrieval, 1 for outline, N/5 for builder (CHUNK_SIZE=5), N/10 for validator (BATCH_SIZE=10)
    question_count = len(questions)
    builder_calls = max(1, (question_count + 4) // 5)
    validator_calls = max(1, (question_count + 9) // 10)
    llm_calls = 1 + 1 + builder_calls + validator_calls  # retrieval + outline + builder + validator

    # ── Comprehensive generation metadata ──────────────────────────────
    generation_metadata = {
        "retrieval_ms": retrieval_ms,
        "outline_ms": outline_ms,
        "build_ms": builder_ms,
        "validate_ms": validator_ms,
        "total_ms": total_ms,
        "llm_calls": llm_calls,
        "tokens_used": total_tokens,
        "cache_hits": 0,  # TODO: populate from Redis cache stats
        "questions_generated": question_count,
        "retry_count": state.get("retry_count", 0),
        "validation_passed": validation_passed,
        "completed_at": time.time(),
    }

    # ── Store in cost_report for frontend ──────────────────────────────
    cost_report["generation_metadata"] = generation_metadata

    warnings.append(f"Pipeline completed — validation: {'passed' if validation_passed else 'partial'}")

    # ── Log comprehensive telemetry ─────────────────────────────────────
    logger.info(
        "Pipeline completed: exam_id=%s, questions=%d, total_ms=%d, "
        "llm_calls=%d, tokens=%d, retrieval_ms=%d, outline_ms=%d, build_ms=%d, validate_ms=%d",
        exam_id, question_count, total_ms, llm_calls, total_tokens,
        retrieval_ms, outline_ms, builder_ms, validator_ms,
    )

    manager = get_connection_manager()
    await _emit_async(manager, exam_id, {
        "type": "completed",
        "exam_id": exam_id,
        "status": "completed",
        "questions_count": len(questions),
        "total_cost_usd": total_cost,
        "generation_metadata": generation_metadata,
    })

    return {
        **state,
        "pipeline_status": PipelineStatus.COMPLETED,
        "cost_report": cost_report,
        "generation_metadata": generation_metadata,
        "approved_questions": questions,
        "warnings": warnings,
    }
