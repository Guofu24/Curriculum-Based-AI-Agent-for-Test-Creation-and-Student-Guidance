"""
Pruning Agent — Over-generation & Pruning

After micro-prompting generates ~30% more questions than needed (the "pool"),
this agent selects the final set matching the original quota.

Selection strategy:
1. Group pool by difficulty bucket (easy/medium/hard)
2. Prioritize validated questions (is_validated=True)
3. Maximize chapter diversity within each bucket
4. Random tie-breaking for fairness
5. Re-number slots sequentially
"""
import random
import logging
from collections import defaultdict

from agents.state import GeneratedQuestion

logger = logging.getLogger(__name__)


class PruningAgent:
    """Selects the best questions from an over-generated pool."""

    def prune_and_select(
        self,
        pool: list[GeneratedQuestion],
        original_quota: dict,
    ) -> list[GeneratedQuestion]:
        """
        Select exactly the requested number of questions per difficulty.

        Args:
            pool: All generated questions (~30% more than needed)
            original_quota: {easy: N, medium: N, hard: N} — original targets

        Returns:
            Final list of questions matching the quota, re-numbered 1..N
        """
        # 1. Bucket questions by difficulty
        buckets = self._bucket_by_difficulty(pool)

        logger.info(
            f"Pruning pool: total={len(pool)}, "
            f"easy={len(buckets['easy'])}, "
            f"medium={len(buckets['medium'])}, "
            f"hard={len(buckets['hard'])}, "
            f"target={original_quota}"
        )

        # 2. Select from each bucket
        selected = []

        for diff, target_count in original_quota.items():
            if target_count <= 0:
                continue

            candidates = buckets.get(diff, [])
            chosen = self._select_diverse(candidates, target_count)
            selected.extend(chosen)

        # 3. Re-number slots sequentially
        selected.sort(key=lambda q: q.difficulty_score)  # order by difficulty
        for i, q in enumerate(selected):
            q.slot_number = i + 1

        logger.info(
            f"Pruning complete: selected {len(selected)} questions "
            f"from pool of {len(pool)}"
        )

        return selected

    def _bucket_by_difficulty(
        self, pool: list[GeneratedQuestion]
    ) -> dict[str, list[GeneratedQuestion]]:
        """Group questions into difficulty buckets based on score."""
        buckets = {"easy": [], "medium": [], "hard": []}

        for q in pool:
            if q.difficulty_score <= 0.3:
                buckets["easy"].append(q)
            elif q.difficulty_score <= 0.6:
                buckets["medium"].append(q)
            else:
                buckets["hard"].append(q)

        return buckets

    def _select_diverse(
        self,
        candidates: list[GeneratedQuestion],
        target_count: int,
    ) -> list[GeneratedQuestion]:
        """
        Select target_count questions prioritizing:
        1. Validated questions first
        2. Diverse chapter coverage
        3. Non-empty content
        """
        if len(candidates) <= target_count:
            return list(candidates)

        # Filter out empty questions
        valid_candidates = [q for q in candidates if q.content.strip()]
        if not valid_candidates:
            return candidates[:target_count]

        # Split into validated and non-validated
        validated = [q for q in valid_candidates if q.is_validated]
        unvalidated = [q for q in valid_candidates if not q.is_validated]

        selected = []

        # Phase 1: Pick validated questions with diverse chapters
        selected.extend(
            self._pick_diverse_chapters(validated, target_count)
        )

        # Phase 2: If not enough, fill from unvalidated
        remaining = target_count - len(selected)
        if remaining > 0:
            # Exclude already-selected slot numbers
            selected_slots = {q.slot_number for q in selected}
            remaining_candidates = [
                q for q in unvalidated if q.slot_number not in selected_slots
            ]
            selected.extend(
                self._pick_diverse_chapters(remaining_candidates, remaining)
            )

        # Phase 3: If still not enough, just take what we can
        remaining = target_count - len(selected)
        if remaining > 0:
            selected_slots = {q.slot_number for q in selected}
            leftovers = [
                q for q in valid_candidates if q.slot_number not in selected_slots
            ]
            random.shuffle(leftovers)
            selected.extend(leftovers[:remaining])

        return selected[:target_count]

    def _pick_diverse_chapters(
        self,
        candidates: list[GeneratedQuestion],
        count: int,
    ) -> list[GeneratedQuestion]:
        """Pick questions maximizing chapter diversity."""
        if not candidates or count <= 0:
            return []

        # Group by chapter (from source_chunks metadata or slot_number context)
        chapter_groups = defaultdict(list)
        for q in candidates:
            # Try to determine chapter from source chunks
            chapter = self._get_chapter(q)
            chapter_groups[chapter].append(q)

        # Round-robin through chapters
        selected = []
        chapters = list(chapter_groups.keys())
        random.shuffle(chapters)

        # Shuffle within each chapter group
        for ch in chapters:
            random.shuffle(chapter_groups[ch])

        idx = 0
        while len(selected) < count:
            ch = chapters[idx % len(chapters)]
            if chapter_groups[ch]:
                selected.append(chapter_groups[ch].pop(0))
            else:
                # This chapter exhausted, remove it
                chapters.remove(ch)
                if not chapters:
                    break
                continue
            idx += 1

        return selected

    def _get_chapter(self, question: GeneratedQuestion) -> str:
        """Extract chapter info from a question's source data."""
        # Try to get from source_chunks if they contain chapter info
        if question.source_chunks:
            return question.source_chunks[0][:10]  # Use chunk ID prefix as proxy
        return "unknown"
