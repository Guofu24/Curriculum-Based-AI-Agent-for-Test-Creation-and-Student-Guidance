from __future__ import annotations

import re

DEFAULT_SUBJECT_LABEL = "Vật lý"
DEFAULT_OUTPUT_LANGUAGE = "vi"
DEFAULT_QUESTION_TYPE = "mcq_single_answer"
PDF_FILE_EXTENSION = ".pdf"
DEFAULT_SECTION_TYPES = (
    "chapter",
    "lesson",
    "topic",
    "subtopic",
    "unknown",
)

_PHYSICS_SUBJECT_ALIASES = {
    "physics",
    "vat ly",
    "vật lý",
    "mon vat ly",
    "môn vật lý",
}


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_physics_subject(subject: str | None) -> str:
    normalized = _normalize_text(subject)
    if normalized in _PHYSICS_SUBJECT_ALIASES:
        return DEFAULT_SUBJECT_LABEL
    raise ValueError("MVP hiện tại chỉ hỗ trợ môn Vật lý")


def normalize_mvp_language(language: str | None) -> str:
    normalized = _normalize_text(language) or DEFAULT_OUTPUT_LANGUAGE
    if normalized in {"vi", "vi-vn", "vietnamese", "tiếng việt", "tieng viet"}:
        return DEFAULT_OUTPUT_LANGUAGE
    raise ValueError("MVP hiện tại chỉ hỗ trợ tiếng Việt")


def require_pdf_extension(file_ext: str | None) -> str:
    normalized = (file_ext or "").strip().lower()
    if normalized and not normalized.startswith("."):
        normalized = f".{normalized}"
    if normalized != PDF_FILE_EXTENSION:
        raise ValueError("MVP hiện tại chỉ hỗ trợ tài liệu PDF")
    return normalized
