"""
Quality Judge Agent — Multi-dimensional Question Assessment

Evaluates generated questions on a comprehensive rubric:
- Answerability: can the question be answered from source?
- Grounding: is the question grounded in source text?
- Clarity: is the question clearly written?
- Ambiguity risk: could it have multiple interpretations?
- Distractor quality: are MCQ distractors plausible and distinct?
- Bloom alignment: does the content match its declared cognitive level?
- Difficulty realism: does complexity match the difficulty score?

Default mode is heuristic (zero LLM calls). LLM-based judging
is reserved for future phases.
"""
import re
import json
import logging
from dataclasses import dataclass, field

from agents.state import GeneratedQuestion
from agents.grounding_checker import GroundingChecker, GroundingReport

logger = logging.getLogger(__name__)

# ── Bloom keyword patterns for alignment checking ───────────────

BLOOM_KEYWORDS: dict[str, set[str]] = {
    "remember": {
        "liệt kê", "nêu", "kể tên", "cho biết", "nhắc lại", "xác định",
        "list", "name", "define", "identify", "recall", "state",
    },
    "understand": {
        "giải thích", "mô tả", "tóm tắt", "so sánh", "phân biệt",
        "explain", "describe", "summarize", "compare", "distinguish",
    },
    "apply": {
        "áp dụng", "sử dụng", "tính toán", "giải quyết", "minh họa",
        "apply", "use", "calculate", "solve", "demonstrate", "compute",
    },
    "analyze": {
        "phân tích", "so sánh", "đối chiếu", "tìm nguyên nhân", "phân loại",
        "analyze", "compare", "contrast", "examine", "categorize",
    },
    "evaluate": {
        "đánh giá", "nhận xét", "phản biện", "ưu điểm", "nhược điểm",
        "evaluate", "assess", "critique", "judge", "argue", "defend",
    },
    "create": {
        "thiết kế", "đề xuất", "xây dựng", "tạo ra", "sáng tạo",
        "design", "propose", "construct", "create", "develop", "formulate",
    },
}

# ── Rubric weights ──────────────────────────────────────────────

WEIGHTS = {
    "answerability": 0.20,
    "grounding": 0.20,
    "clarity": 0.15,
    "ambiguity_risk": 0.10,
    "distractor_quality": 0.15,
    "bloom_alignment": 0.10,
    "difficulty_realism": 0.10,
}

PASS_THRESHOLD = 0.50


@dataclass
class QualityScore:
    """Multi-dimensional quality score for a generated question."""
    slot_number: int
    answerability: float = 0.0
    grounding: float = 0.0
    clarity: float = 0.0
    ambiguity_risk: float = 1.0       # 1.0 = no ambiguity (good)
    distractor_quality: float = 1.0
    bloom_alignment: float = 0.0
    difficulty_realism: float = 0.0
    overall: float = 0.0
    passed: bool = False
    recommendation: str = "keep"      # keep | review | regenerate
    notes: list[str] = field(default_factory=list)


class QualityJudgeAgent:
    """Evaluates question quality using a multi-dimensional rubric."""

    def __init__(self, grounding_checker: GroundingChecker = None, llm=None):
        self.grounding_checker = grounding_checker or GroundingChecker()
        self.llm = llm  # reserved for LLM-based judging (future)

    async def judge_questions(
        self,
        questions: list[GeneratedQuestion],
    ) -> tuple[list[GeneratedQuestion], list[dict], list[dict]]:
        """
        Judge all questions on the rubric.

        Returns:
            (judged_questions, quality_scores_dicts, grounding_report_dicts)
        """
        judged: list[GeneratedQuestion] = []
        scores: list[dict] = []
        grounding_reports: list[dict] = []

        for question in questions:
            grounding = self.grounding_checker.check(question)
            grounding_reports.append(_grounding_to_dict(grounding))

            quality = self._heuristic_judge(question, grounding)
            scores.append(_score_to_dict(quality))

            # Annotate question with judge result
            question.is_validated = question.is_validated and quality.passed
            if not quality.passed:
                _merge_validation_notes(question, quality)

            judged.append(question)

        passed_count = sum(1 for s in scores if s["passed"])
        logger.info(
            f"QualityJudge: {passed_count}/{len(questions)} passed "
            f"(threshold={PASS_THRESHOLD})"
        )

        return judged, scores, grounding_reports

    # ── Heuristic rubric ────────────────────────────────────────────

    def _heuristic_judge(
        self,
        question: GeneratedQuestion,
        grounding: GroundingReport,
    ) -> QualityScore:
        """Rule-based multi-dimensional quality assessment."""
        score = QualityScore(slot_number=question.slot_number)

        score.answerability = self._check_answerability(question, grounding)
        score.grounding = grounding.overall_score
        score.clarity = self._check_clarity(question)
        score.ambiguity_risk = self._check_ambiguity(question)

        if question.question_type == "mcq":
            score.distractor_quality = self._check_distractor_quality(question)
        else:
            score.distractor_quality = 1.0  # N/A for essay

        score.bloom_alignment = self._check_bloom_alignment(question)
        score.difficulty_realism = self._check_difficulty_realism(question)

        # Weighted overall
        score.overall = sum(
            WEIGHTS[dim] * getattr(score, dim)
            for dim in WEIGHTS
        )

        score.passed = score.overall >= PASS_THRESHOLD
        if score.overall >= 0.75:
            score.recommendation = "keep"
        elif score.overall >= PASS_THRESHOLD:
            score.recommendation = "review"
        else:
            score.recommendation = "regenerate"

        return score

    # ── Individual dimension checks ─────────────────────────────────

    def _check_answerability(
        self, question: GeneratedQuestion, grounding: GroundingReport
    ) -> float:
        # Use continuous answer_support_score (Phase 2) instead of boolean
        score = 0.3 + 0.5 * grounding.answer_support_score
        if question.explanation and len(question.explanation) > 10:
            score += 0.1
        return min(1.0, score)

    def _check_clarity(self, question: GeneratedQuestion) -> float:
        content = question.content.strip()
        score = 1.0

        if len(content) < 20:
            score -= 0.4

        has_question_marker = bool(re.search(
            r"[?？]|^(what|which|how|why|when|where|who|explain|describe|"
            r"hãy|nêu|giải thích|cho biết|so sánh|phân tích|đánh giá|trình bày)",
            content.lower(),
        ))
        if not has_question_marker:
            score -= 0.2

        if len(content) > 500:
            score -= 0.1

        # Unclosed code block
        if "```" in content and content.count("```") % 2 != 0:
            score -= 0.15

        return max(0.0, score)

    def _check_ambiguity(self, question: GeneratedQuestion) -> float:
        """1.0 = clear (good), 0.0 = very ambiguous (bad)."""
        content = question.content.lower()
        score = 1.0

        vague_patterns = [
            r"\b(some|nhiều|một số|several|various|certain)\b",
            r"\b(often|sometimes|usually|thường|đôi khi|có thể)\b",
        ]
        for pattern in vague_patterns:
            if re.search(pattern, content):
                score -= 0.15

        # Double negatives
        if re.search(r"(not.*not|không.*không|chẳng.*chẳng)", content):
            score -= 0.3

        # "All / None of the above" in MCQ options
        if question.question_type == "mcq" and question.options:
            for opt in question.options:
                text = opt.get("text", "").lower()
                if any(p in text for p in [
                    "all of the above", "none of the above",
                    "tất cả đều đúng", "không có đáp án nào đúng",
                ]):
                    score -= 0.2
                    break

        return max(0.0, score)

    def _check_distractor_quality(self, question: GeneratedQuestion) -> float:
        if not question.options or len(question.options) != 4:
            return 0.3

        score = 1.0
        correct_label = question.correct_answer.strip()

        # Duplicate option texts
        texts = [opt.get("text", "").strip().lower() for opt in question.options]
        if len(set(texts)) < len(texts):
            score -= 0.3

        # Very short options
        for t in texts:
            if len(t) < 2:
                score -= 0.15

        # Grossly mismatched lengths (correct vs distractors)
        correct_text = ""
        for opt in question.options:
            if opt.get("label") == correct_label:
                correct_text = opt.get("text", "")
                break
        if correct_text:
            clen = len(correct_text)
            for opt in question.options:
                if opt.get("label") == correct_label:
                    continue
                dlen = len(opt.get("text", ""))
                if clen > 0 and dlen > 0:
                    ratio = min(clen, dlen) / max(clen, dlen)
                    if ratio < 0.2:
                        score -= 0.1

        return max(0.0, score)

    def _check_bloom_alignment(self, question: GeneratedQuestion) -> float:
        content = question.content.lower()
        bloom = question.bloom_level.lower()

        if bloom not in BLOOM_KEYWORDS:
            return 0.5

        target_kws = BLOOM_KEYWORDS[bloom]
        has_target = any(kw in content for kw in target_kws)

        other_match = any(
            level != bloom and any(kw in content for kw in kws)
            for level, kws in BLOOM_KEYWORDS.items()
        )

        if has_target:
            return 1.0
        if not other_match:
            return 0.6  # no bloom keywords at all — neutral
        return 0.3      # matches a different bloom level

    def _check_difficulty_realism(self, question: GeneratedQuestion) -> float:
        content = question.content
        word_count = len(content.split())

        has_scenario = bool(re.search(
            r"(tình huống|scenario|given|giả sử|suppose|consider|xét)",
            content.lower(),
        ))
        has_multi_step = bool(re.search(
            r"(và.*và|and.*and|first.*then|trước.*sau|bước)",
            content.lower(),
        ))

        estimated = 0.3
        if has_scenario:
            estimated += 0.2
        if has_multi_step:
            estimated += 0.2
        if word_count > 50:
            estimated += 0.1
        if word_count > 100:
            estimated += 0.1
        estimated = min(1.0, estimated)

        diff = abs(estimated - question.difficulty_score)
        if diff < 0.2:
            return 1.0
        elif diff < 0.4:
            return 0.6
        return 0.3


# ── Helpers (module-level) ──────────────────────────────────────────

def _score_to_dict(score: QualityScore) -> dict:
    return {
        "slot_number": score.slot_number,
        "answerability": round(score.answerability, 3),
        "grounding": round(score.grounding, 3),
        "clarity": round(score.clarity, 3),
        "ambiguity_risk": round(score.ambiguity_risk, 3),
        "distractor_quality": round(score.distractor_quality, 3),
        "bloom_alignment": round(score.bloom_alignment, 3),
        "difficulty_realism": round(score.difficulty_realism, 3),
        "overall": round(score.overall, 3),
        "passed": score.passed,
        "recommendation": score.recommendation,
        "notes": score.notes,
    }


def _grounding_to_dict(report: GroundingReport) -> dict:
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


def _merge_validation_notes(
    question: GeneratedQuestion, quality: QualityScore
) -> None:
    """Append quality judge results into the question's validation_notes."""
    existing: dict = {}
    try:
        if question.validation_notes:
            existing = json.loads(question.validation_notes)
    except (json.JSONDecodeError, TypeError):
        pass

    existing["quality_judge"] = {
        "overall": round(quality.overall, 3),
        "passed": quality.passed,
        "recommendation": quality.recommendation,
        "notes": quality.notes,
    }
    question.validation_notes = json.dumps(existing, ensure_ascii=False)
