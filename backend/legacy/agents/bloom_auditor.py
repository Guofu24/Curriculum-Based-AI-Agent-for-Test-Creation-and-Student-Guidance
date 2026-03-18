"""
Bloom Auditor Agent — Verify Bloom taxonomy level accuracy.

For every generated question, this agent evaluates whether the actual
cognitive demand of the question matches the declared Bloom level.

Uses rule-based keyword analysis + optional LLM verification.

Spec reference: §6.9 mục 2 — Bloom Level Verification
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agents.state import GeneratedQuestion

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# Bloom taxonomy keyword patterns (Vietnamese + English)
# ──────────────────────────────────────────

BLOOM_KEYWORDS: dict[str, list[str]] = {
    "remember": [
        # Vietnamese
        "liệt kê", "kể tên", "nêu", "cho biết", "định nghĩa", "nhận diện",
        "xác định", "gọi tên", "nhắc lại", "trình bày",
        # English
        "list", "name", "define", "identify", "recall", "state", "describe",
        "recognize", "label", "match", "select", "what is",
    ],
    "understand": [
        # Vietnamese
        "giải thích", "phân biệt", "so sánh", "tóm tắt", "mô tả",
        "diễn giải", "minh họa", "phân loại", "suy luận", "ví dụ",
        # English
        "explain", "compare", "contrast", "summarize", "interpret",
        "classify", "illustrate", "paraphrase", "infer", "example",
    ],
    "apply": [
        # Vietnamese
        "áp dụng", "tính toán", "sử dụng", "giải", "thực hiện",
        "xây dựng", "hoàn thành", "vận dụng", "minh chứng", "chứng minh",
        # English
        "apply", "calculate", "solve", "use", "implement", "demonstrate",
        "execute", "modify", "operate", "compute", "build",
    ],
    "analyze": [
        # Vietnamese
        "phân tích", "so sánh", "đánh giá nguyên nhân", "xác định mối quan hệ",
        "phân biệt", "tìm điểm khác biệt", "suy luận", "nhận xét",
        # English
        "analyze", "differentiate", "examine", "break down", "categorize",
        "investigate", "distinguish", "relate", "organize", "cause",
    ],
    "evaluate": [
        # Vietnamese
        "đánh giá", "nhận xét", "phê bình", "biện luận", "chứng minh",
        "bảo vệ quan điểm", "so sánh ưu nhược", "lập luận", "phản bác",
        # English
        "evaluate", "judge", "justify", "critique", "argue", "defend",
        "support", "assess", "recommend", "conclude", "prioritize",
    ],
    "create": [
        # Vietnamese
        "thiết kế", "xây dựng", "đề xuất", "sáng tạo", "lập kế hoạch",
        "phát triển", "tổng hợp", "viết", "soạn", "thiết lập mô hình",
        # English
        "create", "design", "develop", "propose", "construct", "formulate",
        "synthesize", "compose", "plan", "generate", "invent", "produce",
    ],
}

BLOOM_LEVEL_ORDER = ["remember", "understand", "apply", "analyze", "evaluate", "create"]


@dataclass
class BloomAuditResult:
    """Result of Bloom level audit for a single question."""
    slot_number: int
    declared_level: str = ""
    detected_level: str = ""
    level_correct: bool = True
    confidence: float = 1.0
    keyword_signals: dict[str, list[str]] = field(default_factory=dict)
    level_gap: int = 0  # positive = over-claiming, negative = under-claiming
    recommendation: str = "keep"  # keep | review | relabel


class BloomAuditorAgent:
    """
    Verifies Bloom taxonomy accuracy using keyword-based analysis.

    For each question:
    1. Scan question content for Bloom indicator keywords
    2. Score each Bloom level based on keyword frequency
    3. Compare detected level with declared level
    4. Flag mismatches for review or relabeling
    """

    def __init__(self, llm=None):
        self.llm = llm

    async def audit(
        self,
        questions: list[GeneratedQuestion],
        tolerance: int = 1,
    ) -> list[BloomAuditResult]:
        """
        Audit Bloom level accuracy for all questions.

        Args:
            questions: List of generated questions to audit
            tolerance: Allowed gap between declared and detected level
                       (1 = adjacent levels are acceptable)

        Returns:
            List of BloomAuditResult, one per question
        """
        results: list[BloomAuditResult] = []

        for question in questions:
            result = self._audit_single(question, tolerance)
            results.append(result)

        # Summary
        correct_count = sum(1 for r in results if r.level_correct)
        logger.info(
            f"[BLOOM_AUDIT] {correct_count}/{len(results)} questions have "
            f"correct Bloom level (tolerance={tolerance})"
        )

        return results

    def _audit_single(
        self,
        question: GeneratedQuestion,
        tolerance: int,
    ) -> BloomAuditResult:
        """Audit a single question's Bloom level."""
        result = BloomAuditResult(
            slot_number=question.slot_number,
            declared_level=question.bloom_level.lower(),
        )

        # ── Score each Bloom level ──
        text = question.content.lower()
        if question.options:
            for opt in question.options:
                if isinstance(opt, dict):
                    text += " " + str(opt.get("text", "")).lower()

        level_scores: dict[str, float] = {}
        keyword_signals: dict[str, list[str]] = {}

        for level, keywords in BLOOM_KEYWORDS.items():
            score = 0.0
            found: list[str] = []
            for keyword in keywords:
                # Use word boundary matching for short keywords
                pattern = rf"\b{re.escape(keyword)}\b" if len(keyword) > 3 else re.escape(keyword)
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    score += len(matches)
                    found.append(keyword)

            level_scores[level] = score
            if found:
                keyword_signals[level] = found

        result.keyword_signals = keyword_signals

        # ── Determine detected level ──
        if any(level_scores.values()):
            # Weight higher Bloom levels slightly more (apply > remember if equal score)
            weighted_scores = {
                level: score * (1 + 0.05 * BLOOM_LEVEL_ORDER.index(level))
                for level, score in level_scores.items()
            }
            detected = max(weighted_scores, key=weighted_scores.get)
        else:
            # No keywords detected — assume declared level is correct
            detected = result.declared_level

        result.detected_level = detected

        # ── Compare declared vs detected ──
        try:
            declared_idx = BLOOM_LEVEL_ORDER.index(result.declared_level)
        except ValueError:
            declared_idx = 0

        try:
            detected_idx = BLOOM_LEVEL_ORDER.index(detected)
        except ValueError:
            detected_idx = declared_idx

        gap = declared_idx - detected_idx
        result.level_gap = gap
        result.level_correct = abs(gap) <= tolerance

        # ── Confidence and recommendation ──
        total_signals = sum(len(v) for v in keyword_signals.values())
        result.confidence = min(1.0, 0.3 + 0.1 * total_signals)

        if not result.level_correct:
            if abs(gap) > 2:
                result.recommendation = "relabel"
            else:
                result.recommendation = "review"
        else:
            result.recommendation = "keep"

        return result
