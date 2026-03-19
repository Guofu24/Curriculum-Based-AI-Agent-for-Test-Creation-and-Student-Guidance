from __future__ import annotations

import re


_BLOOM_ALIASES: dict[str, str] = {
    "remember": "remember",
    "knowledge": "remember",
    "recall": "remember",
    "memorize": "remember",
    "memorization": "remember",
    "understand": "understand",
    "understanding": "understand",
    "comprehend": "understand",
    "comprehension": "understand",
    "interpret": "understand",
    "explain": "understand",
    "apply": "apply",
    "application": "apply",
    "use": "apply",
    "solve": "apply",
    "calculate": "apply",
    "analyze": "analyze",
    "analyse": "analyze",
    "analysis": "analyze",
    "analyzing": "analyze",
    "analytical": "analyze",
    "evaluate": "evaluate",
    "evaluation": "evaluate",
    "assess": "evaluate",
    "assessment": "evaluate",
    "judge": "evaluate",
    "judgment": "evaluate",
    "create": "create",
    "creation": "create",
    "design": "create",
    "formulate": "create",
    "synthesize": "create",
    "synthesis": "create",
}


def normalize_bloom_level(raw_level, fallback: str = "understand") -> str:
    fallback_text = _normalize_bloom_token(fallback) or "understand"
    fallback_value = _BLOOM_ALIASES.get(fallback_text, "understand")

    if raw_level is None:
        return fallback_value

    value = getattr(raw_level, "value", raw_level)
    normalized = _normalize_bloom_token(value)
    if not normalized:
        return fallback_value

    return _BLOOM_ALIASES.get(normalized, fallback_value)


def _normalize_bloom_token(value) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-]+", "_", text).strip("_")
