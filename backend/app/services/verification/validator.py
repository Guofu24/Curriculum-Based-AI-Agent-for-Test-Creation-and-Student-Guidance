"""
Question validator for the active MVP runtime

Responsibilities:
- Verify each generated question has proper structure and content
- Check: non-empty content, correct_answer present, MCQ has 4 options
- Validate bloom_level and difficulty alignment
- Grounding check via GroundingChecker (hybrid heuristic, active MVP path)
- Avoid extra LLM calls during verification

Output per question (validation_notes JSON):
    basic_rule_pass   â€” structural checks passed?
    grounding_pass    â€” grounding heuristic passed?
    grounding_report  â€” full GroundingReport dict (source traceability, etc.)
    validation_errors â€” list of human-readable issues
    overall_quality   â€” 0.0â€“1.0 composite score
    method            â€” "rule-based+grounding-v2"
"""
import json
import logging

from app.core.runtime_models import GeneratedQuestion
from app.services.verification.grounding_checker import GroundingChecker, GroundingReport

logger = logging.getLogger(__name__)

# Valid bloom levels per difficulty
VALID_BLOOMS = {
    "easy": {"remember", "understand"},
    "medium": {"apply", "analyze"},
    "hard": {"evaluate", "create"},
}


def _grounding_report_to_dict(report: GroundingReport) -> dict:
    """Serialize GroundingReport to a JSON-safe dict."""
    return {
        "slot_number": report.slot_number,
        "lexical_overlap": round(report.lexical_overlap, 3),
        "ngram_overlap": round(report.ngram_overlap, 3),
        "phrase_overlap": round(report.phrase_overlap, 3),
        "answer_support_score": round(report.answer_support_score, 3),
        "answer_supported": report.answer_supported,
        "distractors_valid": report.distractors_valid,
        "verbatim_ratio": round(report.verbatim_ratio, 3),
        "overall_score": round(report.overall_score, 3),
        "grounding_pass": report.grounding_pass,
        "source_traceability": [
            {
                "chunk_index": t.chunk_index,
                "chunk_id": t.chunk_id,
                "stem_overlap": t.stem_overlap,
                "answer_overlap": t.answer_overlap,
                "phrase_match": t.phrase_match,
                "is_best_for_stem": t.is_best_for_stem,
                "is_best_for_answer": t.is_best_for_answer,
            }
            for t in report.source_traceability
        ],
        "distractor_details": [
            {
                "label": d.label,
                "text": d.text,
                "source_overlap": d.source_overlap,
                "phrase_match": d.phrase_match,
                "exceeds_correct": d.exceeds_correct,
            }
            for d in report.distractor_details
        ],
        "details": report.details,
    }


class QuestionValidator:
    """Validates generated questions using rule-based checks (no LLM calls)."""

    QUALITY_THRESHOLD = 0.6

    def __init__(self, llm=None, grounding_checker: GroundingChecker = None):
        # LLM kept for API compatibility but not used by the active validator.
        self.llm = llm
        self.grounding_checker = grounding_checker or GroundingChecker()

    async def validate_questions(
        self,
        questions: list[GeneratedQuestion],
        strict_grounding: bool = True,
    ) -> tuple[list[GeneratedQuestion], dict]:
        """
        Validate all questions with rule-based + grounding checks.

        Returns (validated_questions, summary).
        Each question's validation_notes is a JSON string with:
        - basic_rule_pass, grounding_pass, grounding_report,
          validation_errors, overall_quality, method
        """
        validated = []
        total_passed = 0
        total_failed = 0
        all_issues: list[str] = []

        for question in questions:
            # â”€â”€ Step 1: structural rule checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            rule_issues = self._check_basic_rules(question)
            basic_rule_pass = len(rule_issues) == 0

            # â”€â”€ Step 2: grounding checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            grounding_report: GroundingReport | None = None
            grounding_issues: list[str] = []

            if strict_grounding and question.source_texts:
                grounding_report = self.grounding_checker.check(question)
                grounding_issues = self._interpret_grounding(grounding_report)

            grounding_pass = len(grounding_issues) == 0

            # â”€â”€ Step 3: Bloom alignment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            bloom_issues = self._check_bloom_alignment(question)

            # â”€â”€ Combine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            all_q_issues = rule_issues + grounding_issues + bloom_issues
            quality = self._compute_quality(question, all_q_issues)

            question.is_validated = quality >= self.QUALITY_THRESHOLD
            question.warnings = list(all_q_issues)
            question.verification_status = (
                "passed" if question.is_validated else "failed"
            )
            question.validation_notes = json.dumps({
                "basic_rule_pass": basic_rule_pass,
                "grounding_pass": grounding_pass,
                "grounding_report": (
                    _grounding_report_to_dict(grounding_report)
                    if grounding_report else None
                ),
                "validation_errors": all_q_issues,
                "warnings": all_q_issues,
                "verification_status": question.verification_status,
                "overall_quality": round(quality, 3),
                "method": "rule-based+grounding-v2",
            }, ensure_ascii=False)

            validated.append(question)

            if question.is_validated:
                total_passed += 1
            else:
                total_failed += 1
                all_issues.extend(all_q_issues)

        summary = {
            "total": len(questions),
            "passed": total_passed,
            "failed": total_failed,
            "hallucination_flags": [],
            "pass_rate": total_passed / len(questions) if questions else 0,
        }

        logger.info(
            f"Validation (rule+grounding-v2): {total_passed}/{len(questions)} "
            f"passed (pass_rate={summary['pass_rate']:.2f})"
        )

        return validated, summary

    # â”€â”€ Structural rule checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _check_basic_rules(self, question: GeneratedQuestion) -> list[str]:
        """Run structural rule-based checks on a single question."""
        issues: list[str] = []

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
                    f"MCQ must have 4 options, got "
                    f"{len(question.options) if question.options else 0}"
                )
            else:
                # Check options have label and text
                for opt in question.options:
                    if not isinstance(opt, dict):
                        issues.append("MCQ options must be objects with label/text")
                        break
                    if not opt.get("label") or not opt.get("text"):
                        issues.append("MCQ option missing label or text")
                        break

                # correct_answer should be one of the option labels
                labels = {
                    opt.get("label")
                    for opt in question.options
                    if isinstance(opt, dict)
                }
                if question.correct_answer not in labels:
                    issues.append(
                        f"correct_answer '{question.correct_answer}' "
                        f"not in option labels {labels}"
                    )
        return issues

    # â”€â”€ Grounding interpretation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _interpret_grounding(self, report: GroundingReport) -> list[str]:
        """Convert GroundingReport into a list of issues (empty = pass)."""
        issues: list[str] = []

        if not report.grounding_pass:
            issues.append(
                f"Low grounding score ({report.overall_score:.0%}): "
                f"question may not be grounded in source"
            )

        if not report.answer_supported:
            issues.append(
                f"Correct answer weakly supported "
                f"(support_score={report.answer_support_score:.2f})"
            )

        if not report.distractors_valid:
            bad = [d.label for d in report.distractor_details if d.exceeds_correct]
            if bad:
                issues.append(
                    f"Distractor(s) {bad} may be more supported "
                    f"than correct answer"
                )

        if report.verbatim_ratio >= 0.70:
            issues.append(
                f"Question too close to source text "
                f"(verbatimâ‰ˆ{report.verbatim_ratio:.0%})"
            )

        return issues

    # â”€â”€ Bloom alignment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _check_bloom_alignment(self, question: GeneratedQuestion) -> list[str]:
        """Check Bloom level vs difficulty score alignment."""
        issues: list[str] = []
        if question.bloom_level and question.difficulty_score is not None:
            bloom = question.bloom_level.lower()
            expected_blooms = VALID_BLOOMS.get(
                self._score_to_bucket(question.difficulty_score), set()
            )
            if expected_blooms and bloom not in expected_blooms:
                issues.append(
                    f"Bloom level '{bloom}' unusual for difficulty "
                    f"{question.difficulty_score:.2f}"
                )
        return issues

    # â”€â”€ Quality score â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _compute_quality(
        self, question: GeneratedQuestion, issues: list[str]
    ) -> float:
        """Compute quality score from rule checks (0.0 to 1.0)."""
        score = 1.0
        score -= len(issues) * 0.25
        if question.explanation and len(question.explanation) > 5:
            score += 0.1
        return max(0.0, min(1.0, score))

    @staticmethod
    def _score_to_bucket(score: float) -> str:
        """Convert difficulty score to bucket label."""
        if score <= 0.3:
            return "easy"
        elif score <= 0.6:
            return "medium"
        return "hard"


ValidatorAgent = QuestionValidator

