"""Scope checker skill - verifies questions are within the selected scope."""

import re
import unicodedata
from app.observability.tracer import get_tracer

# Vietnamese + English stop words for meaningful-word filtering
_STOP_WORDS = frozenset({
    "mot", "la", "cua", "co", "va", "voi", "cac", "duoc", "trong", "de",
    "khong", "cho", "nay", "do", "khi", "tu", "nhu", "theo", "hay", "hoac",
    "thi", "ma", "ve", "ra", "da", "se", "bi", "con", "den", "boi",
    "nao", "day", "len", "xuong", "vao", "tai", "tren", "duoi", "nen",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "of", "in", "to", "for",
    "on", "at", "by", "with", "from", "as", "or", "and", "but", "not",
    "that", "this", "it", "its",
})


def _normalize(text: str) -> str:
    """NFD-strip diacritics and lowercase."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _meaningful_words(text: str) -> set[str]:
    """Extract non-stop words (length >= 2) from text."""
    words = set(re.findall(r'\b[a-z0-9]{2,}\b', _normalize(text)))
    return words - _STOP_WORDS


def _word_trigrams(text: str) -> set[tuple]:
    """Word-level trigrams for verbatim-copy detection."""
    words = re.findall(r'\b[a-z0-9]+\b', _normalize(text))
    if len(words) < 3:
        return set()
    return {(words[i], words[i + 1], words[i + 2]) for i in range(len(words) - 2)}


class ScopeCheckerSkill:
    """
    Deterministic local scope checker — no LLM calls (quota-safe).

    Returns a result dict with 'is_hard_fail' so ValidatorAgent can apply
    the two-tier policy:
      - is_hard_fail=True  → add to all_issues → trigger retry
      - is_hard_fail=False → needs_review only, no retry
    """

    @get_tracer().skill_span("scope_checker")
    async def check(
        self,
        question_stem: str,
        allowed_content: list[dict],
        scope_chapters: list[str],
    ) -> dict:
        """Legacy interface — delegates to _local_check."""
        return self._local_check(question_text=question_stem, primary_chunks=allowed_content)

    def _local_check(
        self,
        question_text: str,
        primary_chunks: list[dict],
    ) -> dict:
        """
        Deterministic scope check using word overlap against primary chunks only.

        Thresholds:
          overlap >= 4 meaningful words  → in_scope (matched)
          overlap 2-3                    → uncertain (soft flag)
          overlap < 2                    → no_primary_evidence (hard fail)
          no primary_chunks              → no_grounding_context (hard fail)
        """
        if not primary_chunks:
            return {
                "in_scope": False,
                "confidence": 0.9,
                "violation_type": "no_grounding_context",
                "evidence_chunk_ids": [],
                "reasoning": "Không có primary chunks — không thể xác minh phạm vi kiến thức.",
                "is_hard_fail": True,
            }

        if not question_text.strip():
            return {
                "in_scope": True,
                "confidence": 0.3,
                "violation_type": None,
                "evidence_chunk_ids": [],
                "reasoning": "Câu hỏi rỗng — bỏ qua kiểm tra scope.",
                "is_hard_fail": False,
            }

        q_words = _meaningful_words(question_text)
        best_overlap = 0
        matching_ids: list[str] = []

        for chunk in primary_chunks[:20]:  # cap to avoid O(n²)
            chunk_words = _meaningful_words(chunk.get("content", ""))
            overlap = len(q_words & chunk_words)
            if overlap > best_overlap:
                best_overlap = overlap
            if overlap >= 4:
                matching_ids.append(chunk.get("chunk_id", "unknown"))

        if matching_ids:
            return {
                "in_scope": True,
                "confidence": min(0.5 + best_overlap * 0.05, 0.9),
                "violation_type": None,
                "evidence_chunk_ids": matching_ids[:3],
                "reasoning": f"{len(matching_ids)} chunk có overlap ≥ 4 từ có nghĩa.",
                "is_hard_fail": False,
            }

        if best_overlap >= 2:
            return {
                "in_scope": True,  # benefit of the doubt
                "confidence": 0.35,
                "violation_type": None,
                "evidence_chunk_ids": [],
                "reasoning": f"Overlap yếu ({best_overlap} từ) — không đủ để xác nhận hoặc từ chối.",
                "is_hard_fail": False,
            }

        return {
            "in_scope": False,
            "confidence": 0.7,
            "violation_type": "no_primary_evidence",
            "evidence_chunk_ids": [],
            "reasoning": f"Không tìm thấy primary chunk có overlap đủ mạnh (best={best_overlap} từ).",
            "is_hard_fail": True,
        }

    async def run(
        self,
        question_stem: str,
        allowed_content: list[dict],
        scope_chapters: list[str],
    ) -> dict:
        """Alias for check() to match skill interface."""
        return await self.check(question_stem, allowed_content, scope_chapters)
