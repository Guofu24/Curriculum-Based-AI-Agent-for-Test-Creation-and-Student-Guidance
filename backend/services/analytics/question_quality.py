from __future__ import annotations

from collections.abc import Iterable


def _normalized_warnings(question) -> list[str]:
    raw = getattr(question, "warnings_json", None)
    if raw is None:
        raw = getattr(question, "warnings", None)
    return [str(item).strip().lower() for item in (raw or []) if str(item).strip()]


def _source_evidence(question) -> list[dict]:
    raw = getattr(question, "source_evidence_json", None)
    if raw is None:
        raw = getattr(question, "source_evidence", None)
    return [item for item in (raw or []) if isinstance(item, dict)]


def _options(question) -> list[dict]:
    return [item for item in (getattr(question, "options", None) or []) if isinstance(item, dict)]


def _has_phrase(warnings: list[str], *phrases: str) -> bool:
    return any(phrase in warning for phrase in phrases for warning in warnings)


def question_error_categories(
    question,
    *,
    duplicate_slots: Iterable[int] | None = None,
) -> list[str]:
    warnings = _normalized_warnings(question)
    evidence = _source_evidence(question)
    options = _options(question)
    duplicate_slot_set = {int(slot) for slot in (duplicate_slots or [])}
    question_number = int(
        getattr(question, "question_number", None)
        or getattr(question, "slot_number", None)
        or 0
    )
    correct_answer = str(getattr(question, "correct_answer", "") or "").strip().upper()
    grounding_report = getattr(question, "grounding_report_json", None) or {}

    categories: list[str] = []

    if _has_phrase(
        warnings,
        "outside the selected section scope",
        "scope leak",
        "outside scope",
    ):
        categories.append("scope_leak")

    if (
        not evidence
        or _has_phrase(
            warnings,
            "grounding",
            "answerable",
            "answer supported",
            "weakly supported",
            "missing evidence",
        )
    ):
        categories.append("weak_evidence")

    if (
        len(options) != 4
        or correct_answer not in {"A", "B", "C", "D"}
        or _has_phrase(
            warnings,
            "correct_answer",
            "option labels",
            "valid single-answer mcq",
            "4 options",
        )
    ):
        categories.append("wrong_answer_key")

    if _has_phrase(
        warnings,
        "distractor",
        "ambiguous",
        "more supported than correct answer",
    ):
        categories.append("ambiguous_options")

    if question_number in duplicate_slot_set or _has_phrase(
        warnings,
        "duplicate another item",
        "duplicates another",
    ):
        categories.append("duplicate_question")

    verbatim_ratio = 0.0
    if isinstance(grounding_report, dict):
        try:
            verbatim_ratio = float(grounding_report.get("verbatim_ratio") or 0.0)
        except (TypeError, ValueError):
            verbatim_ratio = 0.0
    if verbatim_ratio >= 0.7 or _has_phrase(warnings, "too close to source", "verbatim"):
        categories.append("verbatim_copy")

    return categories
