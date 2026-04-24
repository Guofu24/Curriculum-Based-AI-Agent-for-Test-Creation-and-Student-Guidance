"""Validator Agent - validates generated questions."""

import time
import json
from typing import Any

from app.agents.base import AgentStatus, AgentMetrics, TokenUsage, ValidatorOutput
from app.agents.llm import get_llm_client
from app.agents.skills.bloom_classifier import BloomClassifierSkill
from app.agents.skills.scope_checker import ScopeCheckerSkill
from app.agents.memory.short_term import ShortTermMemory
from app.observability.tracer import get_tracer
from app.core.config import get_settings

settings = get_settings()
tracer = get_tracer()


# G9: Max retry loops before giving up
MAX_VALIDATION_RETRIES = 3


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

    def __init__(self, redis=None):
        self.llm = get_llm_client()
        self.bloom_skill = BloomClassifierSkill()
        self.scope_skill = ScopeCheckerSkill()
        # G9: ShortTermMemory for persisting retry issues across Celery worker restarts
        self.short_term = ShortTermMemory(redis) if redis else None

    @tracer.agent_span("validator_agent")
    async def validate(
        self,
        questions: list[dict],
        exam_config: dict,
        retrieved_context: list[dict] | None = None,
        trace_id: str = "",
    ) -> ValidatorOutput:
        """
        Validate all questions.

        G9: Issues are persisted to Redis via ShortTermMemory so they survive
        Celery worker restarts. Max 3 retry loops enforced.
        """
        start_time = time.time()
        trace_id = trace_id or str(time.time())
        metrics = AgentMetrics(trace_id=trace_id)
        warnings: list[str] = []
        exam_id = trace_id.split("_retry_")[0]  # Strip retry suffix for key
        issues: list[dict] = []  # G9: accumulate from skills + LLM

        try:
            # G9: Load persisted retry issues from Redis before validation
            prior_issues: list[dict] = []
            if self.short_term:
                try:
                    prior_issues = await self.short_term.load_retry_issues(exam_id)
                    if prior_issues:
                        warnings.append(
                            f"Loaded {len(prior_issues)} prior issues from Redis "
                            f"(from previous retry attempt)"
                        )
                except Exception:
                    pass

            # Apply bloom_classifier skill to each question
            for q in questions:
                try:
                    bloom_result = await self.bloom_skill.run(
                        question_stem=q.get("stem", ""),
                        question_type=q.get("type", "mcq"),
                    )
                    q["bloom_classified"] = bloom_result.get("bloom_level")
                    # Track bloom mismatch as issue
                    expected_bloom = q.get("bloom_level", "")
                    actual_bloom = bloom_result.get("bloom_level", "")
                    if expected_bloom and actual_bloom and expected_bloom != actual_bloom:
                        issues.append({
                            "question_id": q.get("question_id", ""),
                            "issue_type": "bloom_mismatch",
                            "detail": f"Expected bloom '{expected_bloom}', classified as '{actual_bloom}'",
                            "suggestion": "Review bloom level classification",
                        })
                except Exception:
                    pass

            # Apply scope_checker skill to each question
            for q in questions:
                try:
                    scope_result = await self.scope_skill.run(
                        question_stem=q.get("stem", ""),
                        allowed_content=retrieved_context or [],
                        scope_chapters=exam_config.get("scope", []),
                    )
                    if not scope_result.get("in_scope", True):
                        issues.append({
                            "question_id": q.get("question_id", ""),
                            "issue_type": "scope_violation",
                            "detail": scope_result.get("reasoning", "Out of scope"),
                            "suggestion": "Restrict to allowed scope",
                        })
                except Exception as e:
                    warnings.append(f"Scope check failed for question {q.get('question_id', '?')}: {e}")

            # G9: Save current issues to Redis before returning
            if self.short_term and issues:
                try:
                    await self.short_term.save_retry_issues(exam_id, issues)
                except Exception:
                    pass

            # Build validation prompt
            prompt = self._build_validation_prompt(questions, exam_config, retrieved_context)

            # Call LLM for validation
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.VALIDATOR_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                role="validator",
                max_tokens=6000,
                temperature=0.1,
            )

            result = json.loads(response)

            validation_passed = result.get("validation_passed", False)
            issues_data = result.get("issues", [])
            bloom_compliance = result.get("bloom_compliance", {})
            scope_violations = result.get("scope_violations", [])
            approved_for_publish = result.get("approved_for_publish", False)

            # Build LLM issues, then MERGE with skill-found issues (don't overwrite)
            llm_issues = [
                ValidationIssue(
                    question_id=i.get("question_id", ""),
                    issue_type=i.get("issue_type", "unknown"),
                    detail=i.get("detail", ""),
                    suggestion=i.get("suggestion", ""),
                ).to_dict()
                for i in issues_data
            ]
            # Merge: keep all skill issues + all LLM issues (no deduplication to preserve audit trail)
            issues = issues + llm_issues

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
            # Bug-015 fix: save skill-found issues even when LLM parsing fails
            if self.short_term and issues:
                try:
                    await self.short_term.save_retry_issues(exam_id, issues)
                except Exception:
                    pass
            return ValidatorOutput(
                status=AgentStatus.PARTIAL,
                agent_name="validator",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                validation_passed=False,
                issues=issues,
                bloom_compliance={},
                scope_violations=[],
                approved_for_publish=False,
            )

        except Exception as e:
            warnings.append(f"Validation failed: {str(e)}")
            # Bug-015 fix: save skill-found issues even when validation throws unexpected error
            if self.short_term and issues:
                try:
                    await self.short_term.save_retry_issues(exam_id, issues)
                except Exception:
                    pass
            return ValidatorOutput(
                status=AgentStatus.PARTIAL,
                agent_name="validator",
                execution_time_ms=int((time.time() - start_time) * 1000),
                token_usage=TokenUsage(),
                warnings=warnings,
                trace_id=trace_id,
                validation_passed=False,
                issues=issues,
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


# ─── Unit test (runnable with: python -m pytest backend/app/agents/validator.py -v -k test_scope_violation) ───
# def test_scope_violation_detected():
#     """
#     Scenario: Question references Chapter 5 but allowed scope is only Chapter 1-3.
#
#     Setup:
#       questions = [
#           {
#               "question_id": "MCQ_001",
#               "stem": "Một vật chuyển động tròn đều có gia tốc hướng tâm a = 4 m/s², "
#                       "bán kính quỹ đạo r = 2 m. Tính tốc độ góc của vật.",
#               "type": "mcq",
#           }
#       ]
#       exam_config = {"scope": ["Chương 1: Động học chất điểm",
#                                "Chương 2: Động lực học chất điểm",
#                                "Chương 3: Tĩnh học"]}
#       retrieved_context = [
#           {"chunk_id": "c1", "content": "Chương 1: Động học chất điểm — các khái niệm cơ bản..."},
#           {"chunk_id": "c2", "content": "Chương 2: Động lực học chất điểm — các định luật Newton..."},
#           {"chunk_id": "c3", "content": "Chương 3: Tĩnh học — điều kiện cân bằng..."},
#       ]
#
#     Expected behaviour:
#       - scope_skill.run() → {"in_scope": False, "violation_type": "out_of_scope", ...}
#       - ValidatorAgent.validate() → issues contains a scope_violation entry for MCQ_001
#       - validation_passed = False (because scope issue was found)
#
#     Notes:
#       - validate_blueprint() is NOT called here (it's on the outline agent).
#       - The issue from scope_skill must be MERGED with any LLM-found issues
#         (not overwritten). See: issues = issues + llm_issues
# """
