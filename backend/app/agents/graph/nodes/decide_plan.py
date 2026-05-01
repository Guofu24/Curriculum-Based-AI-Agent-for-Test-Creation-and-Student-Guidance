"""decide_plan — G6: Determine if request is complex (needs Planner) or simple."""

import logging

from app.agents.graph.state import ExamGraphState

logger = logging.getLogger("app.agents.graph")


async def decide_plan(state: ExamGraphState) -> ExamGraphState:
    """
    G6: Decide whether to use the Planner Agent.

    Checks for complexity signals in the user prompt and exam config.
    Returns "complex" → use PlannerAgent. Returns "simple" → use default plan.

    Signals (>=2 = complex):
      1. Prompt exists and has content
      2. Prompt length > 200
      3. Contains keywords: tập trung, thực tế, ưu tiên, hạn chế, tránh
      4. extra_instructions is non-empty
      5. bloom_distribution is set AND prompt length > 100

    Bug-001 fix: signal[0] is now correctly bool(user_prompt.strip())
      instead of the erroneous (user_prompt or "") > "" comparison.

    Args:
        state: Must contain user_prompt, exam_config.

    Returns:
        Updated ExamGraphState with plan_type set to "complex" or "simple".
    """
    user_prompt = state.get("user_prompt") or ""
    exam_config = state.get("exam_config", {})

    signals = [
        bool(user_prompt and user_prompt.strip()),
        len(user_prompt) > 200,
        any(kw in user_prompt for kw in ["tập trung", "thực tế", "ưu tiên", "hạn chế", "tránh"]),
        exam_config.get("extra_instructions") not in (None, ""),
        exam_config.get("bloom_distribution") is not None and len(user_prompt) > 100,
    ]

    plan_type = "complex" if sum(signals) >= 2 else "simple"

    logger.info("Plan decision: %s (signals=%s)", plan_type, signals)

    return {
        **state,
        "plan_type": plan_type,
    }
