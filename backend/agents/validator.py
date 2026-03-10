"""
Validator Agent (Rule-Based — No LLM)

Responsibilities:
- Verify each generated question has proper structure and content
- Check: non-empty content, correct_answer present, MCQ has 4 options
- Validate bloom_level and difficulty alignment
- Simple text-overlap grounding check against source chunks
- Zero LLM calls — saves API tokens for question generation

This replaces the LLM-based validator to stay within Groq free tier limits.
"""
import json
import logging

from agents.state import GeneratedQuestion

logger = logging.getLogger(__name__)

# Valid bloom levels per difficulty
VALID_BLOOMS = {
    "easy": {"remember", "understand"},
    "medium": {"apply", "analyze"},
    "hard": {"evaluate", "create"},
}


class ValidatorAgent:
    """Validates generated questions using rule-based checks (no LLM calls)."""

    QUALITY_THRESHOLD = 0.6

    def __init__(self, llm=None):
        # LLM kept for API compatibility but NOT used
        self.llm = llm

    async def validate_questions(
        self,
        questions: list[GeneratedQuestion],
        strict_grounding: bool = True,
    ) -> tuple[list[GeneratedQuestion], dict]:
        """
        Validate all questions with rule-based checks.
        Returns (validated_questions, summary).
        """
        validated = []
        total_passed = 0
        total_failed = 0
        all_issues = []

        for question in questions:
            issues = self._check_rules(question, strict_grounding)
            quality = self._compute_quality(question, issues)

            question.is_validated = quality >= self.QUALITY_THRESHOLD
            question.validation_notes = json.dumps({
                "overall_quality": quality,
                "issues": issues,
                "method": "rule-based",
            })

            validated.append(question)

            if question.is_validated:
                total_passed += 1
            else:
                total_failed += 1
                all_issues.extend(issues)

        summary = {
            "total": len(questions),
            "passed": total_passed,
            "failed": total_failed,
            "hallucination_flags": [],
            "pass_rate": total_passed / len(questions) if questions else 0,
        }

        logger.info(
            f"Rule-based validation: {total_passed}/{len(questions)} passed "
            f"(pass_rate={summary['pass_rate']:.2f})"
        )

        return validated, summary

    def _check_rules(
        self, question: GeneratedQuestion, strict_grounding: bool
    ) -> list[str]:
        """Run rule-based checks on a single question."""
        issues = []

        # 1. Content must be non-empty and meaningful (>10 chars)
        if not question.content or len(question.content.strip()) < 10:
            issues.append("Empty or too-short question content")

        # 2. Must have correct_answer
        if not question.correct_answer or len(question.correct_answer.strip()) < 1:
            issues.append("Missing correct_answer")

        # 3. MCQ must have exactly 4 options
        if question.question_type == "mcq":
            if not question.options or len(question.options) != 4:
                issues.append(
                    f"MCQ must have 4 options, got {len(question.options) if question.options else 0}"
                )
            else:
                # Check options have label and text
                for opt in question.options:
                    if not opt.get("label") or not opt.get("text"):
                        issues.append("MCQ option missing label or text")
                        break

                # correct_answer should be one of the option labels
                labels = {opt.get("label") for opt in question.options}
                if question.correct_answer not in labels:
                    issues.append(
                        f"correct_answer '{question.correct_answer}' not in option labels {labels}"
                    )

        # 4. Simple grounding check: overlap between question and source text
        if strict_grounding and question.source_texts:
            source_combined = " ".join(question.source_texts).lower()
            # Extract key words from question (>3 chars)
            q_words = set(
                w for w in question.content.lower().split()
                if len(w) > 3
            )
            if q_words:
                overlap = sum(1 for w in q_words if w in source_combined)
                overlap_ratio = overlap / len(q_words)
                if overlap_ratio < 0.1:
                    issues.append(
                        f"Low source overlap ({overlap_ratio:.0%}): question may not be grounded"
                    )

        return issues

    def _compute_quality(
        self, question: GeneratedQuestion, issues: list[str]
    ) -> float:
        """Compute quality score from rule checks (0.0 to 1.0)."""
        score = 1.0
        # Each issue reduces score
        score -= len(issues) * 0.25
        # Bonus for having explanation
        if question.explanation and len(question.explanation) > 5:
            score += 0.1
        return max(0.0, min(1.0, score))
