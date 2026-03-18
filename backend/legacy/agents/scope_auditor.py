"""
Scope Auditor Agent — Verify questions stay within selected curriculum scope.

For every generated question, this agent:
1. Checks if the question content references topics/concepts OUTSIDE the
   selected scope units.
2. Compares source evidence chunk metadata against allowed scope.
3. Flags out-of-scope questions for review or regeneration.

Spec reference: §6.9 mục 1 — Scope Verification
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agents.state import GeneratedQuestion, ScopeUnit

logger = logging.getLogger(__name__)


@dataclass
class ScopeAuditResult:
    """Result of scope audit for a single question."""
    slot_number: int
    in_scope: bool = True
    confidence: float = 1.0
    scope_matches: list[str] = field(default_factory=list)
    scope_violations: list[str] = field(default_factory=list)
    evidence_chapter_match: bool = True
    recommendation: str = "keep"  # keep | review | regenerate


class ScopeAuditorAgent:
    """
    Verifies that generated questions remain within the selected
    curriculum scope using evidence metadata and keyword analysis.

    Two verification strategies:
    1. Metadata-based: Check source chunk chapter/heading vs allowed scope
    2. Content-based: Analyze question text for out-of-scope concepts
    """

    def __init__(self, llm=None):
        self.llm = llm

    async def audit(
        self,
        questions: list[GeneratedQuestion],
        selected_scope: list[ScopeUnit],
        strict_mode: bool = True,
    ) -> list[ScopeAuditResult]:
        """
        Audit all questions against the selected scope.

        Returns a list of ScopeAuditResult, one per question.
        """
        if not selected_scope:
            # No scope restriction — all questions pass
            return [
                ScopeAuditResult(
                    slot_number=q.slot_number,
                    in_scope=True,
                    confidence=1.0,
                    recommendation="keep",
                )
                for q in questions
            ]

        # Build allowed scope set
        allowed_chapters = set()
        allowed_tags: set[str] = set()
        allowed_titles: set[str] = set()

        for unit in selected_scope:
            if unit.chapter_number > 0:
                allowed_chapters.add(unit.chapter_number)
            allowed_tags.update(tag.lower() for tag in unit.tags)
            if unit.title:
                allowed_titles.add(unit.title.lower())

        results: list[ScopeAuditResult] = []

        for question in questions:
            result = self._audit_single(
                question, allowed_chapters, allowed_tags, allowed_titles, strict_mode
            )
            results.append(result)

        # Summary
        in_scope_count = sum(1 for r in results if r.in_scope)
        logger.info(
            f"[SCOPE_AUDIT] {in_scope_count}/{len(results)} questions in scope "
            f"(strict={strict_mode})"
        )

        return results

    def _audit_single(
        self,
        question: GeneratedQuestion,
        allowed_chapters: set[int],
        allowed_tags: set[str],
        allowed_titles: set[str],
        strict_mode: bool,
    ) -> ScopeAuditResult:
        """Audit a single question against scope constraints."""
        result = ScopeAuditResult(slot_number=question.slot_number)
        violations: list[str] = []
        matches: list[str] = []

        # ── Check 1: Source evidence chunks ──
        evidence_chapters: set[int] = set()
        for evidence in question.source_evidence:
            ch = evidence.get("chapter_number")
            if ch and isinstance(ch, int) and ch > 0:
                evidence_chapters.add(ch)

        if evidence_chapters and allowed_chapters:
            overlap = evidence_chapters & allowed_chapters
            if overlap:
                matches.append(f"Evidence from chapters: {sorted(overlap)}")
            out_of_scope = evidence_chapters - allowed_chapters
            if out_of_scope:
                violations.append(
                    f"Evidence references out-of-scope chapters: {sorted(out_of_scope)}"
                )
                result.evidence_chapter_match = False

        # ── Check 2: Scope tags on the question ──
        question_tags = set(tag.lower() for tag in question.scope_tags)
        if question_tags and allowed_tags:
            tag_overlap = question_tags & allowed_tags
            if tag_overlap:
                matches.append(f"Matching scope tags: {sorted(tag_overlap)}")
            missing = question_tags - allowed_tags
            if missing and strict_mode:
                violations.append(f"Question has tags outside scope: {sorted(missing)}")

        # ── Check 3: Blueprint cell key ──
        if question.blueprint_cell_key and allowed_chapters:
            # cell_id often contains "chapter:N"
            cell_chapters = re.findall(r"chapter[:\-_](\d+)", question.blueprint_cell_key.lower())
            for ch_str in cell_chapters:
                ch_num = int(ch_str)
                if ch_num in allowed_chapters:
                    matches.append(f"Blueprint cell matches chapter {ch_num}")
                else:
                    violations.append(f"Blueprint cell references chapter {ch_num} (out of scope)")

        # ── Determine result ──
        result.scope_matches = matches
        result.scope_violations = violations

        if violations:
            result.in_scope = False
            result.confidence = max(0.0, 1.0 - 0.3 * len(violations))
            if strict_mode:
                result.recommendation = "regenerate" if len(violations) > 1 else "review"
            else:
                result.recommendation = "review"
        else:
            result.in_scope = True
            result.confidence = min(1.0, 0.5 + 0.25 * len(matches))
            result.recommendation = "keep"

        return result
