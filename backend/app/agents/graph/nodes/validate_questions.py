"""validate_questions — Agent 4: Validator Agent."""

import logging

from app.agents.graph.state import ExamGraphState, AgentRole
from app.agents.graph.nodes._emit import _emit

logger = logging.getLogger("app.agents.graph")


async def validate_questions(state: ExamGraphState) -> ExamGraphState:
    """
    Agent 4: Validate generated questions.

    Calls ValidatorAgent.validate() which performs 3 checks:
      1. Bloom compliance (bloom_classifier_skill)
      2. Scope violation (scope_checker_skill)
      3. LLM-based answer checking

    Bug-015 fix in ValidatorAgent: skill-found issues are saved to Redis even
    when LLM parsing fails or throws unexpected errors, so retry works correctly.

    Bug-008 fix: issues deduplication ensures same question_id + issue_type
    appears only once in retry_issues.

    Args:
        state: Must contain questions, exam_config, retrieved_context.

    Returns:
        Updated ExamGraphState with validation_result, retry_issues.
    """
    from app.agents.validator import ValidatorAgent, is_retryable_validation_issue

    from app.core.redis_client import get_redis_client
    redis_client = get_redis_client()
    questions = state.get("questions", [])
    exam_config = state.get("exam_config", {})
    retrieved_context = state.get("retrieved_context", [])
    exam_id = state.get("exam_id", "")
    cost_report = dict(state.get("cost_report", {}))
    warnings = list(state.get("warnings", []))

    validator_agent = ValidatorAgent(redis=redis_client)

    def _validator_emit(event: dict) -> None:
        _emit(state, event)

    validation_result = await validator_agent.validate(
        questions=questions,
        exam_config=exam_config,
        retrieved_context=retrieved_context,
        trace_id=exam_id,
        emit_fn=_validator_emit,
    )

    # Bug-008 fix: deduplicate issues by (question_id, issue_type)
    all_issues = list(getattr(validation_result, "issues", []))
    seen: dict[tuple, dict] = {}
    for issue in all_issues:
        key = (issue.get("question_id", ""), issue.get("issue_type", ""))
        if key not in seen:
            seen[key] = issue
    deduplicated_issues = list(seen.values())
    retryable_issues = [
        issue for issue in deduplicated_issues
        if is_retryable_validation_issue(issue)
    ]

    cost_report["validator"] = validation_result.token_usage.model_dump()

    _emit(state, {
        "type": "validation_result",
        "passed": validation_result.status.value == "success",
        "issues_count": len(deduplicated_issues),
        "issues": deduplicated_issues,
    })

    # Publish targeted rebuild instructions directly to BuilderAgent (peer-to-peer)
    if retryable_issues:
        try:
            from app.agents.messaging import AgentMessageBus
            bus = AgentMessageBus(redis_client)
            await bus.publish(
                exam_id=exam_id,
                sender="validator",
                recipient="builder",
                message_type="targeted_rebuild",
                payload={
                    "issues": retryable_issues,
                    "failed_question_ids": list({i.get("question_id") for i in retryable_issues}),
                    "correction_strategies": {
                        i.get("question_id"): i.get("correction_strategy", "")
                        for i in retryable_issues
                        if i.get("correction_strategy")
                    },
                },
            )
        except Exception as _e:
            logger.debug("targeted_rebuild publish failed (non-critical): %s", _e)

    return {
        **state,
        "validation_result": {
            "status": validation_result.status.value,
            "validation_passed": validation_result.status.value == "success",
            "issues": deduplicated_issues,
            "bloom_compliance": getattr(validation_result, "bloom_compliance", {}),
            "scope_violations": getattr(validation_result, "scope_violations", []),
            "warnings": validation_result.warnings or [],
        },
        "retry_issues": retryable_issues,
        "cost_report": cost_report,
        "current_agent": AgentRole.VALIDATOR,
        "warnings": warnings + (validation_result.warnings or []),
        "updated_at": state.get("updated_at"),
    }

