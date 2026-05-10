"""Planner Agent - creates dynamic execution plan."""

import time
import json
from typing import Any

from app.agents.base import AgentBaseOutput, AgentStatus, AgentMetrics, TokenUsage, PlannerOutput
from app.agents.llm import get_llm_client
from app.observability.tracer import get_tracer
from app.core.config import get_settings

settings = get_settings()
tracer = get_tracer()


class PlanStep:
    """Represents a single step in the execution plan."""

    def __init__(
        self,
        step: int,
        tool: str,
        params_override: dict | None = None,
        note: str = "",
    ):
        self.step = step
        self.tool = tool
        self.params_override = params_override or {}
        self.note = note

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "tool": self.tool,
            "params_override": self.params_override,
            "note": self.note,
        }


# Default execution plan for simple requests
DEFAULT_PLAN = [
    PlanStep(1, "tool_retrieve_context", {}, "Standard retrieval"),
    PlanStep(2, "tool_outline_exam", {}, "Standard outline"),
    PlanStep(3, "tool_build_questions", {}, "Standard question generation"),
    PlanStep(4, "tool_validate_exam", {}, "Standard validation"),
]


class PlannerAgent:
    """
    Planner Agent - dynamic execution planning.

    Role: Between Orchestrator and sub-agents. Analyzes requirements
    and creates a dynamic execution plan instead of hardcoded pipeline.

    When to call:
    - Complex prompts (many specific requirements)
    - Batch edit requests
    - Simple prompts → Orchestrator dispatches directly, skip Planner

    Output: Execution Plan with tool sequence and parameter overrides.
    """

    PLANNER_SYSTEM_PROMPT = """Bạn là chuyên gia lập kế hoạch thực thi cho hệ thống multi-agent.

Nhiệm vụ:
1. Phân tích yêu cầu của giảng viên
2. Quyết định bước nào cần thiết, bước nào skip, bước nào lặp lại
3. Tạo execution plan với thứ tự tool và parameter overrides
4. Ước lượng token cost
5. Quyết định HITL checkpoint ở bước nào

Available tools:
- tool_retrieve_context: Truy xuất kiến thức từ vector DB
- tool_outline_exam: Tạo sườn đề (blueprint)
- tool_build_questions: Sinh câu hỏi từ blueprint
- tool_validate_exam: Kiểm tra đề

Plan rules:
- tool_retrieve_context luôn chạy TRƯỚC tool_outline_exam
- tool_outline_exam luôn chạy TRƯỚC tool_build_questions
- tool_build_questions luôn chạy TRƯỚC tool_validate_exam
- HITL checkpoint sau tool_outline_exam (Checkpoint 1: Blueprint Review)
- Có thể skip tool_retrieve_context nếu context đã có
- Có thể tăng/giảm web_search_quota cho tool_build_questions

Output format:
{
  "plan": [
    {
      "step": 1,
      "tool": "tool_retrieve_context",
      "params_override": {"bloom_targets": ["van_dung", "van_dung_cao"]},
      "note": "Tăng focus vào van_dung"
    },
    ...
  ],
  "estimated_token_cost": 35000,
  "hitl_checkpoint_after_step": 2
}"""

    def __init__(self):
        self.llm = get_llm_client()

    @tracer.agent_span("planner_agent")
    async def create_plan(
        self,
        user_request: str,
        exam_config: dict,
        available_tools: list[str] | None = None,
        constraints: dict | None = None,
        trace_id: str = "",
    ) -> PlannerOutput:
        """Create a dynamic execution plan."""
        start_time = time.time()
        trace_id = trace_id or str(time.time())
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []
        available_tools = available_tools or [
            "tool_retrieve_context",
            "tool_outline_exam",
            "tool_build_questions",
            "tool_validate_exam",
        ]
        constraints = constraints or {
            "max_web_search_calls": settings.AGENT_MAX_WEB_SEARCH_CALLS,
            "token_budget": settings.AGENT_TOKEN_BUDGET,
        }

        try:
            # Build prompt
            user_prompt = f"""Phân tích yêu cầu và tạo execution plan:

## User Request:
{user_request}

## Exam Config:
{json.dumps(exam_config, ensure_ascii=False, indent=2)}

## Available Tools:
{json.dumps(available_tools, ensure_ascii=False, indent=2)}

## Constraints:
{json.dumps(constraints, ensure_ascii=False, indent=2)}

Tạo execution plan:"""

            # Call LLM
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                role="planner",
                max_tokens=4000,
                temperature=0.2,
            )

            result = json.loads(response)

            plan_data = result.get("plan", [])
            plan = [
                PlanStep(
                    step=p.get("step", i + 1),
                    tool=p.get("tool", ""),
                    params_override=p.get("params_override", {}),
                    note=p.get("note", ""),
                ).to_dict()
                for i, p in enumerate(plan_data)
            ]

            estimated_cost = result.get("estimated_token_cost", 0)
            hitl_checkpoint = result.get("hitl_checkpoint_after_step")

            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = metrics.prompt_tokens + metrics.completion_tokens

            return PlannerOutput(
                status=AgentStatus.SUCCESS,
                agent_name="planner",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(
                    prompt_tokens=metrics.prompt_tokens,
                    completion_tokens=metrics.completion_tokens,
                    total_tokens=usage,
                ),
                warnings=warnings,
                trace_id=trace_id,
                plan=plan,
                estimated_token_cost=estimated_cost,
                hitl_checkpoint_after_step=hitl_checkpoint,
            )

        except Exception as e:
            warnings.append(f"Planner failed: {str(e)}. Using default plan.")
            elapsed_ms = int((time.time() - start_time) * 1000)

            return PlannerOutput(
                status=AgentStatus.PARTIAL,
                agent_name="planner",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                plan=self.get_default_plan(),
                estimated_token_cost=0,
                hitl_checkpoint_after_step=None,
            )

    def is_complex_request(self, user_prompt: str, exam_config: dict) -> bool:
        """
        G6: Determine if request is complex enough to need Planner Agent.
        Returns True when sum(signals) >= 2.
        """
        signals = [
            len(user_prompt) > 200,
            any(kw in user_prompt for kw in ["tập trung", "thực tế", "ưu tiên", "hạn chế", "tránh"]),
            exam_config.get("extra_instructions") not in (None, ""),
            exam_config.get("bloom_distribution") is not None and len(user_prompt) > 100,
        ]
        return sum(signals) >= 2

    def get_default_plan(self) -> list[dict]:
        """Get the default execution plan."""
        return [step.to_dict() for step in DEFAULT_PLAN]
