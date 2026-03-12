"""
Dedup Filter — Semantic Similarity Detection & Removal

Groups near-duplicate questions and selects the best representative from
each group. Uses text-based heuristics (no external ML dependencies):
1. Word-level Jaccard similarity
2. SequenceMatcher ratio (difflib, stdlib)
3. Answer-target similarity
"""
import logging
from difflib import SequenceMatcher
from dataclasses import dataclass, field

from agents.state import GeneratedQuestion

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    """A cluster of near-duplicate questions."""
    representative_slot: int
    member_slots: list[int] = field(default_factory=list)
    max_similarity: float = 0.0


class DedupFilterAgent:
    """Detects and removes near-duplicate questions."""

    SIMILARITY_THRESHOLD = 0.65

    def __init__(self, threshold: float = None):
        if threshold is not None:
            self.SIMILARITY_THRESHOLD = threshold

    def filter_duplicates(
        self,
        questions: list[GeneratedQuestion],
        quality_scores: list[dict] = None,
    ) -> tuple[list[GeneratedQuestion], list[dict]]:
        """
        Detect duplicates and keep the best representative from each group.

        Args:
            questions: Pool of questions to deduplicate.
            quality_scores: Optional quality scores for tie-breaking
                            (from QualityJudge).

        Returns:
            (filtered_questions, duplicate_groups_as_dicts)
        """
        if len(questions) <= 1:
            return list(questions), []

        # Quality score lookup
        score_map: dict[int, float] = {}
        if quality_scores:
            for qs in quality_scores:
                score_map[qs["slot_number"]] = qs.get("overall", 0.5)

        n = len(questions)
        removed = set()          # indices that have been merged away
        groups: list[DuplicateGroup] = []

        for i in range(n):
            if i in removed:
                continue

            cluster = [i]
            for j in range(i + 1, n):
                if j in removed:
                    continue
                sim = self._compute_similarity(questions[i], questions[j])
                if sim >= self.SIMILARITY_THRESHOLD:
                    cluster.append(j)

            if len(cluster) > 1:
                # Keep the member with the highest quality score
                best_idx = max(
                    cluster,
                    key=lambda idx: score_map.get(
                        questions[idx].slot_number, 0.5
                    ),
                )

                groups.append(DuplicateGroup(
                    representative_slot=questions[best_idx].slot_number,
                    member_slots=[
                        questions[idx].slot_number
                        for idx in cluster if idx != best_idx
                    ],
                    max_similarity=max(
                        self._compute_similarity(
                            questions[best_idx], questions[idx]
                        )
                        for idx in cluster if idx != best_idx
                    ),
                ))

                # Mark non-best members as removed
                for idx in cluster:
                    if idx != best_idx:
                        removed.add(idx)

        # Build filtered list
        filtered = [q for i, q in enumerate(questions) if i not in removed]

        # Serializable group dicts
        group_dicts = [
            {
                "representative_slot": g.representative_slot,
                "member_slots": g.member_slots,
                "max_similarity": round(g.max_similarity, 3),
            }
            for g in groups
        ]

        logger.info(
            f"DedupFilter: {len(questions)} → {len(filtered)} questions "
            f"({len(groups)} duplicate group(s) merged)"
        )

        return filtered, group_dicts

    # ── Similarity computation ──────────────────────────────────────

    def _compute_similarity(
        self, q1: GeneratedQuestion, q2: GeneratedQuestion
    ) -> float:
        """Combined similarity: content words + sequence + answer."""
        content_jac = self._word_jaccard(q1.content, q2.content)
        seq_sim = self._sequence_similarity(q1.content, q2.content)
        answer_sim = self._answer_similarity(q1, q2)

        return 0.4 * content_jac + 0.3 * seq_sim + 0.3 * answer_sim

    def _word_jaccard(self, text1: str, text2: str) -> float:
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union) if union else 0.0

    def _sequence_similarity(self, text1: str, text2: str) -> float:
        if not text1 or not text2:
            return 0.0
        # Cap length to avoid slow comparison on very long questions
        return SequenceMatcher(
            None, text1[:500].lower(), text2[:500].lower()
        ).ratio()

    def _answer_similarity(
        self, q1: GeneratedQuestion, q2: GeneratedQuestion
    ) -> float:
        """Check whether two questions target the same answer / concept."""
        # MCQ: compare correct-option texts
        if q1.question_type == "mcq" and q2.question_type == "mcq":
            t1 = self._correct_option_text(q1)
            t2 = self._correct_option_text(q2)
            if t1 and t2:
                return SequenceMatcher(
                    None, t1.lower()[:200], t2.lower()[:200]
                ).ratio()

        # Essay / mixed: compare correct_answer strings
        if q1.correct_answer and q2.correct_answer:
            return SequenceMatcher(
                None,
                q1.correct_answer.lower()[:200],
                q2.correct_answer.lower()[:200],
            ).ratio()
        return 0.0

    @staticmethod
    def _correct_option_text(question: GeneratedQuestion) -> str:
        if not question.options or not question.correct_answer:
            return ""
        for opt in question.options:
            if opt.get("label") == question.correct_answer.strip():
                return opt.get("text", "")
        return ""
