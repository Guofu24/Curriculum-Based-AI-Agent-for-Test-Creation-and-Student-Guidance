"""
Review Impact Analyzer — Classify Partial Edit Semantic Drift (Phase 4)

Classifies each edit request into one of three impact levels:
- **cosmetic**: Typo fixes, formatting, punctuation — no semantic change.
  → Validator + QualityJudge only (no retrieval refresh needed).
- **moderate**: Rephrasing, clarifying options, minor content tweaks.
  → Validator + QualityJudge (existing source context is sufficient).
- **strong**: Topic change, difficulty shift, Bloom level change, full
  regeneration of many questions.
  → RetrievalRefresh + Validator + QualityJudge to prevent drift.

The overall impact level is the **maximum** across all edit requests.
No LLM calls — pure heuristic classification.
"""
import re
import logging

from agents.state import GeneratedQuestion

logger = logging.getLogger(__name__)

# ── Keyword patterns for classification ─────────────────────────

_COSMETIC_PATTERNS = re.compile(
    r"(typo|lỗi chính tả|chính tả|sửa lỗi|fix\s*typo|format|định dạng|"
    r"dấu\s*(câu|chấm|phẩy)|spacing|indent|capitalize|viết hoa|viết thường|"
    r"punctuation|chấm\s*câu|xuống\s*dòng)",
    re.IGNORECASE,
)

_STRONG_PATTERNS = re.compile(
    r"(chuyển\s*(sang|qua)\s*chương|change\s*topic|đổi\s*chủ\s*đề|"
    r"thay\s*đổi\s*chủ\s*đề|chủ\s*đề\s*khác|different\s*topic|"
    r"khó\s*hơn|dễ\s*hơn|harder|easier|tăng.*độ\s*khó|giảm.*độ\s*khó|"
    r"change\s*difficulty|đổi\s*(mức|level)|bloom|"
    r"viết\s*lại\s*(hoàn\s*toàn|toàn\s*bộ|tất\s*cả)|rewrite\s*all|"
    r"regenerate\s*all|tạo\s*lại\s*(hết|toàn\s*bộ))",
    re.IGNORECASE,
)


class ReviewImpactAnalyzer:
    """Classifies the semantic impact of partial edit requests."""

    # If more than this fraction of questions are edited → strong
    BULK_EDIT_THRESHOLD = 0.5

    def classify(
        self,
        edit_requests: list[dict],
        existing_questions: list[GeneratedQuestion],
    ) -> str:
        """
        Return the overall impact level: 'cosmetic', 'moderate', or 'strong'.

        Takes the maximum across all individual edit request classifications.
        """
        if not edit_requests:
            return "cosmetic"

        total_questions = len(existing_questions)
        edited_count = self._count_edited_questions(
            edit_requests, total_questions,
        )

        # Bulk edit → strong regardless of prompt content
        if total_questions > 0 and edited_count / total_questions > self.BULK_EDIT_THRESHOLD:
            logger.info(
                f"Impact=strong: bulk edit ({edited_count}/{total_questions} "
                f"questions, >{self.BULK_EDIT_THRESHOLD:.0%})"
            )
            return "strong"

        # Classify each request by prompt content
        levels = [self._classify_single(req) for req in edit_requests]

        overall = "cosmetic"
        for lvl in levels:
            if lvl == "strong":
                overall = "strong"
                break
            if lvl == "moderate":
                overall = "moderate"

        logger.info(
            f"Impact={overall}: {len(edit_requests)} edit request(s), "
            f"{edited_count} question(s) affected, "
            f"per-request levels={levels}"
        )
        return overall

    def _classify_single(self, edit_request: dict) -> str:
        """Classify a single edit request by its prompt keywords."""
        prompt = edit_request.get("edit_prompt", "").strip()
        edit_type = edit_request.get("edit_type", "regenerate")

        # No prompt → depends on edit_type
        if not prompt:
            return "moderate" if edit_type == "regenerate" else "cosmetic"

        # Check strong patterns first (higher priority)
        if _STRONG_PATTERNS.search(prompt):
            return "strong"

        # Check cosmetic patterns
        if _COSMETIC_PATTERNS.search(prompt):
            return "cosmetic"

        # Default: moderate (prompt has content but no strong/cosmetic signal)
        return "moderate"

    def _count_edited_questions(
        self,
        edit_requests: list[dict],
        total_questions: int,
    ) -> int:
        """Count distinct questions targeted by all edit requests."""
        edited: set[int] = set()
        for req in edit_requests:
            if req.get("question_ids"):
                for qid in req["question_ids"]:
                    try:
                        edited.add(int(qid))
                    except (ValueError, TypeError):
                        pass
            start = req.get("range_start")
            end = req.get("range_end")
            if start is not None and end is not None:
                for n in range(int(start), int(end) + 1):
                    edited.add(n)
        return len(edited)
