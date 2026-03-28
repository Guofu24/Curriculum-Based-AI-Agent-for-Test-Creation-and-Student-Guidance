"""Validator Agent - validates generated questions."""

import time
import json
from typing import Any

from app.agents.base import AgentStatus, AgentMetrics, TokenUsage, ValidatorOutput
from app.agents.llm import get_llm_client
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.scope_checker import ScopeCheckerSkill
from app.core.config import get_settings

settings = get_settings()


class ValidationIssue:
    """Represents a validation issue."""

    def __init__(
        self,
        question_id: str,
        issue_type: str,
        detail: str,
        suggestion: str,
    ):
        self.question_id = question_id
        self.issue_type = issue_type
        self.detail = detail
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "issue_type": self.issue_type,
            "detail": self.detail,
            "suggestion": self.suggestion,
        }


class ValidatorAgent:
    """
    Agent 4: Validator Agent (the "critic")

    Role: Review all generated questions and perform 3 checks:
    1. Answer Checking: LLM solves each question → compare with proposed answer
    2. Bloom Compliance: bloom_classifier_skill verifies Bloom level
    3. Scope Violation: scope_checker_skill checks for out-of-scope knowledge

    Retry Logic:
    - If validation fails → return issues list
    - Orchestrator retries Builder with issues (max 3 rounds)
    - If still failing → partial result with warning
    """

    VALIDATOR_SYSTEM_PROMPT = """Bạn là giáo viên phản biện chuyên nghiệp.

Nhiệm vụ:
1. Đọc toàn bộ đề đã sinh
2. Thực sự GIẢI từng câu (không chỉ đọc đáp án đề xuất)
3. Kiểm tra 3 khía cạnh:
   a) **Answer Checking**: Đáp án đúng phải chính xác
   b) **Bloom Compliance**: Câu hỏi có đúng mức Bloom đã khai báo không
   c) **Scope Violation**: Câu hỏi có dùng kiến thức ngoài phạm vi không

Output format:
{
  "validation_passed": true/false,
  "issues": [
    {
      "question_id": "MCQ_015",
      "issue_type": "wrong_answer" | "bloom_mismatch" | "scope_violation" | "duplicate",
      "detail": "Mô tả lỗi cụ thể",
      "suggestion": "Đề xuất cách sửa"
    }
  ],
  "score_attempt": {
    "MCQ_001": {"model_answer": "B", "correct": true},
    "MCQ_002": {"model_answer": "A", "expected": "C", "correct": false}
  },
  "bloom_compliance": {
    "nhan_biet": {"expected": 20, "actual": 18, "ok": false},
    "van_dung_cao": {"expected": 20, "actual": 22, "ok": true}
  },
  "scope_violations": ["MCQ_015: sử dụng định luật ngoài scope"],
  "approved_for_publish": false
}"""

    def __init__(self):
        self.llm = get_llm_client()
        self.bloom_skill = BloomClassifierSkill()
        self.scope_skill = ScopeCheckerSkill()

    async def validate(
        self,
        questions: list[dict],
        exam_config: dict,
        retrieved_context: list[dict] | None = None,
        trace_id: str = "",
    ) -> ValidatorOutput:
        """Validate all questions."""
        start_time = time.time()
        trace_id = trace_id or str(time.time())
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []

        try:
            # Build validation prompt
            prompt = self._build_validation_prompt(questions, exam_config, retrieved_context)

            # Call LLM for validation
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.VALIDATOR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=settings.OPENAI_MODEL_VALIDATOR,
                response_format={"type": "json_object"},
                max_tokens=6000,
                temperature=0.1,
            )

            metrics.prompt_tokens = response["usage"]["prompt_tokens"]
            metrics.completion_tokens = response["usage"]["completion_tokens"]

            result = json.loads(response["content"])

            validation_passed = result.get("validation_passed", False)
            issues_data = result.get("issues", [])
            bloom_compliance = result.get("bloom_compliance", {})
            scope_violations = result.get("scope_violations", [])
            approved_for_publish = result.get("approved_for_publish", False)

            # Convert issues to proper format
            issues = [
                ValidationIssue(
                    question_id=i.get("question_id", ""),
                    issue_type=i.get("issue_type", "unknown"),
                    detail=i.get("detail", ""),
                    suggestion=i.get("suggestion", ""),
                ).to_dict()
                for i in issues_data
            ]

            # Check bloom compliance
            bloom_dist = exam_config.get("bloom_distribution", {})
            for bloom, config in bloom_dist.items():
                if bloom in bloom_compliance:
                    compliance = bloom_compliance[bloom]
                    expected = config
                    actual = compliance.get("actual", 0)
                    if abs(expected - actual) > 2:
                        warnings.append(
                            f"Bloom '{bloom}': expected {expected}, actual {actual} (diff > 2)"
                        )

            elapsed_ms = int((time.time() - start_time) * 1000)
            usage = metrics.prompt_tokens + metrics.completion_tokens

            status = AgentStatus.SUCCESS
            if not validation_passed:
                if len(issues) > 0:
                    status = AgentStatus.RETRY_NEEDED
                else:
                    status = AgentStatus.PARTIAL

            return ValidatorOutput(
                status=status,
                agent_name="validator",
                execution_time_ms=elapsed_ms,
                token_usage=TokenUsage(
                    prompt_tokens=metrics.prompt_tokens,
                    completion_tokens=metrics.completion_tokens,
                    total_tokens=usage,
                ),
                warnings=warnings,
                trace_id=trace_id,
                validation_passed=validation_passed,
                issues=issues,
                bloom_compliance=bloom_compliance,
                scope_violations=scope_violations,
                approved_for_publish=approved_for_publish,
            )

        except json.JSONDecodeError as e:
            warnings.append(f"Failed to parse validation result: {e}")
            return ValidatorOutput(
                status=AgentStatus.PARTIAL,
                agent_name="validator",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                validation_passed=False,
                issues=[],
                bloom_compliance={},
                scope_violations=[],
                approved_for_publish=False,
            )

        except Exception as e:
            warnings.append(f"Validation failed: {str(e)}")
            return ValidatorOutput(
                status=AgentStatus.PARTIAL,
                agent_name="validator",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                validation_passed=False,
                issues=[],
                bloom_compliance={},
                scope_violations=[],
                approved_for_publish=False,
            )

    def _build_validation_prompt(
        self,
        questions: list[dict],
        exam_config: dict,
        retrieved_context: list[dict] | None,
    ) -> str:
        """Build the validation prompt."""
        scope = exam_config.get("scope", [])
        bloom_dist = exam_config.get("bloom_distribution", {})

        # Format questions
        questions_json = json.dumps(questions, ensure_ascii=False, indent=2)

        # Format context
        context_str = ""
        if retrieved_context:
            context_chunks = [
                f"[{c.get('chunk_id', '?')}] {c.get('content', '')[:300]}"
                for c in retrieved_context[:20]
            ]
            context_str = "\n\n".join(context_chunks)

        prompt = f"""Kiểm tra đề kiểm tra sau:

## Exam Config:
- Scope: {json.dumps(scope, ensure_ascii=False)}
- Bloom distribution: {json.dumps(bloom_dist, ensure_ascii=False, indent=2)}

## Questions:
{questions_json}

## Retrieved Context (allowed knowledge):
{context_str or "No context available."}

Thực hiện kiểm tra:"""

        return prompt
