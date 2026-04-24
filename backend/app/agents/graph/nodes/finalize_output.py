"""finalize_output — Final node: emit completed event and prepare return value."""

import logging

from app.agents.graph.state import ExamGraphState, PipelineStatus
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def finalize_output(state: ExamGraphState) -> ExamGraphState:
    """
    Final node: finalize the pipeline output.

    Calculates total tokens and cost, emits the completed event,
    and sets pipeline_status to COMPLETED.

    Args:
        state: Must contain questions, blueprint, distribution_summary, cost_report.

    Returns:
        Updated state with pipeline_status = COMPLETED and all final metrics.
    """
    questions = state.get("questions", [])
    blueprint = state.get("blueprint", [])
    distribution_summary = state.get("distribution_summary", {})
    cost_report = dict(state.get("cost_report", {}))
    warnings = list(state.get("warnings", []))
    validation_passed = state.get("validation_result", {}).get("validation_passed", False)

    # Calculate totals
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

    warnings.append(f"Pipeline completed — validation: {'passed' if validation_passed else 'partial'}")

    _emit(state, {
        "type": "completed",
        "exam_id": state.get("exam_id", ""),
        "status": "completed",
        "questions_count": len(questions),
        "total_cost_usd": total_cost,
    })

    return {
        **state,
        "pipeline_status": PipelineStatus.COMPLETED,
        "cost_report": cost_report,
        "approved_questions": questions,
        "warnings": warnings,
    }

