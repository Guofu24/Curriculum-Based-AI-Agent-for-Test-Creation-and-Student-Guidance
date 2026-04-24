"""clarification_check — G1: Check if requirements are clear."""

import json
import logging

from app.agents.graph.state import ExamGraphState, PipelineStatus

logger = logging.getLogger("app.agents.graph")


async def clarification_check(state: ExamGraphState) -> ExamGraphState:
    """
    G1: Check if user requirements are clear.

    Calls LLM to determine if clarification questions are needed.
    If requirements are unclear, sets pipeline_status to CLARIFICATION_NEEDED,
    which triggers a conditional edge to emit_clarification.

    Args:
        state: Must contain user_prompt, exam_config.

    Returns:
        Updated ExamGraphState with pipeline_status set appropriately.
    """
    user_prompt = state.get("user_prompt") or ""
    exam_config = state.get("exam_config", {})

    CLARIFY_PROMPT = """Bạn là giảng viên đang giao nhiệm vụ tạo đề kiểm tra.

Nếu yêu cầu chưa rõ ràng, hãy đặt tối đa 3 câu hỏi làm rõ:
- Scope (phạm vi bài kiểm tra)
- Số lượng và loại câu hỏi
- Mức độ phân bổ Bloom
- Yêu cầu đặc biệt nào khác

Trả về JSON:
{
  "clarification_questions": [
    {"question_id": "q1", "question": "..."}
  ],
  "requirements_clear": true/false
}"""

    clarity_prompt = f"""Yêu cầu hiện tại:
Prompt: {user_prompt}
Config: {json.dumps(exam_config, ensure_ascii=False, indent=2)}

Xác định xem yêu cầu đã rõ ràng chưa."""

    messages = [
        {"role": "system", "content": CLARIFY_PROMPT},
        {"role": "user", "content": clarity_prompt},
    ]

    try:
        from app.agents.llm import get_llm_client
        client = get_llm_client()
        response = await client.chat(
            messages=messages,
            role="planner",
            max_tokens=1000,
            temperature=0.3,
        )
        result = json.loads(response)
        if not result.get("requirements_clear", True):
            questions = result.get("clarification_questions", [])
            if questions:
                return {
                    **state,
                    "pipeline_status": PipelineStatus.CLARIFICATION_NEEDED,
                    "checkpoint_0_requirements": {"clarification_questions": questions[:3]},
                    "warnings": state.get("warnings", []) + ["Requirements unclear - clarification needed"],
                }
    except Exception as exc:
        logger.warning("Clarification check failed: %s", exc)

    return {
        **state,
        "pipeline_status": PipelineStatus.RUNNING,
        "checkpoint_0_status": "approved",  # type: ignore
        "checkpoint_0_requirements": {
            "scope": state.get("scope", []),
            "exam_config": state.get("exam_config", {}),
        },
    }
