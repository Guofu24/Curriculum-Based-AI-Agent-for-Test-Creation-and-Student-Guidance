"""plan_complex — Call PlannerAgent for dynamic execution plan."""

import logging

from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


async def plan_complex(state: ExamGraphState) -> ExamGraphState:
    """
    Called when plan_type == "complex".

    Invokes PlannerAgent.create_plan() to generate a dynamic execution plan
    tailored to the user's specific request.

    Args:
        state: Must contain user_prompt, exam_config, exam_id.

    Returns:
        Updated ExamGraphState with execution_plan and cost_report["planner"].
    """
    user_prompt = state.get("user_prompt") or ""
    exam_config = state.get("exam_config", {})
    exam_id = state.get("exam_id", "")
    cost_report = dict(state.get("cost_report", {}))

    warnings = list(state.get("warnings", []))

    try:
        from app.agents.planner import PlannerAgent
        planner = PlannerAgent()
        result = await planner.create_plan(
            user_request=user_prompt,
            exam_config=exam_config,
            trace_id=exam_id,
        )
        execution_plan = result.model_dump().get("plan", [])
        cost_report["planner"] = result.token_usage.model_dump()
    except Exception as exc:
        logger.warning("PlannerAgent failed, falling back to default plan: %s", exc)
        from app.agents.planner import PlannerAgent
        planner = PlannerAgent()
        execution_plan = planner.get_default_plan()
        warnings.append(f"Planner failed: {exc} — using default plan")

    return {
        **state,
        "execution_plan": execution_plan,
        "cost_report": cost_report,
        "warnings": warnings,
    }
