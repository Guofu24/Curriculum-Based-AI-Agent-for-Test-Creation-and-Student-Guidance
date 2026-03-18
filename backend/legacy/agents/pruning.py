"""
Pruning Agent.

Selects the final question set from an over-generated pool while preserving
blueprint-cell quotas as closely as possible.
"""
import logging

from agents.state import GeneratedQuestion

logger = logging.getLogger(__name__)


class PruningAgent:
    """Select the best questions from an over-generated pool."""

    def prune_and_select(
        self,
        pool: list[GeneratedQuestion],
        original_quota: dict,
    ) -> list[GeneratedQuestion]:
        if not pool or not original_quota:
            return list(pool)

        selected: list[GeneratedQuestion] = []
        grouped = self._group_by_cell(pool)
        shortages: dict[str, int] = {}

        for cell_key, target_count in original_quota.items():
            candidates = grouped.get(cell_key, [])
            chosen = self._select_for_cell(candidates, target_count)
            selected.extend(chosen)
            if len(chosen) < target_count:
                shortages[cell_key] = target_count - len(chosen)

        selected.sort(key=lambda question: question.slot_number)
        for question_number, question in enumerate(selected, start=1):
            question.slot_number = question_number

        if shortages:
            logger.warning("Pruning shortages by blueprint cell: %s", shortages)
        logger.info(
            "Pruning complete: selected %s/%s questions across %s blueprint cells",
            len(selected),
            len(pool),
            len(original_quota),
        )
        return selected

    def _group_by_cell(self, pool: list[GeneratedQuestion]) -> dict[str, list[GeneratedQuestion]]:
        grouped: dict[str, list[GeneratedQuestion]] = {}
        for question in pool:
            key = question.blueprint_cell_key or "unassigned"
            grouped.setdefault(key, []).append(question)
        return grouped

    def _select_for_cell(
        self,
        candidates: list[GeneratedQuestion],
        target_count: int,
    ) -> list[GeneratedQuestion]:
        if target_count <= 0:
            return []

        ranked = sorted(
            candidates,
            key=lambda question: (
                int(bool(question.is_validated)),
                -(len(question.warnings or [])),
                1 if question.verification_status == "passed" else 0,
                -float(question.difficulty_score),
                -int(bool(question.content.strip())),
            ),
            reverse=True,
        )
        return ranked[:target_count]
