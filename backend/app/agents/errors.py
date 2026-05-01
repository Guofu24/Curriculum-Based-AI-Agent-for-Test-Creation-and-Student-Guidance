"""Error taxonomy for LLM calls — enables targeted retry strategies."""

from enum import Enum


class LLMErrorType(str, Enum):
    """Classification of LLM call failures."""
    PARSE_ERROR = "PARSE_ERROR"           # Response doesn't parse to expected schema
    VALIDATION_FAILED = "VALIDATION_FAILED"  # Parse OK but validation rules failed
    RATE_LIMIT = "RATE_LIMIT"           # Provider rate limit hit
    TIMEOUT = "TIMEOUT"                 # LLM call exceeded timeout
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"  # Input too long for context window
    PROVIDER_ERROR = "PROVIDER_ERROR"     # Generic provider-side error
    UNKNOWN = "UNKNOWN"                  # Unclassified error


class LLMErrors:
    """Utilities for classifying and handling LLM errors."""

    @staticmethod
    def classify(error: Exception, response_text: str = "") -> LLMErrorType:
        """Classify an exception into an LLMErrorType."""
        error_str = str(error).lower()
        response_lower = response_text.lower()

        # Context overflow
        if any(kw in error_str for kw in ["context", "maximum", "too long", "token limit", "input too long"]):
            return LLMErrorType.CONTEXT_OVERFLOW

        # Timeout
        if any(kw in error_str for kw in ["timeout", "timed out", "deadline"]):
            return LLMErrorType.TIMEOUT

        # Rate limit
        if any(kw in error_str for kw in ["rate limit", "rate_limit", "429", "too many requests", "quota"]):
            return LLMErrorType.RATE_LIMIT

        # Provider errors
        if any(kw in error_str for kw in ["500", "502", "503", "504", "internal server", "service unavailable", "bad gateway"]):
            return LLMErrorType.PROVIDER_ERROR

        # Parse error (from response_text check)
        if response_text:
            try:
                import json
                json.loads(response_text)
            except Exception:
                # Response exists but can't parse — likely a parse error
                if response_text.strip():
                    return LLMErrorType.PARSE_ERROR

        return LLMErrorType.UNKNOWN

    @staticmethod
    def get_retry_strategy(error_type: LLMErrorType) -> dict:
        """Get retry strategy for a given error type."""
        strategies = {
            LLMErrorType.PARSE_ERROR: {
                "should_retry": True,
                "max_retries": 2,
                "strategy": "Use stricter output instruction + JSON schema",
            },
            LLMErrorType.VALIDATION_FAILED: {
                "should_retry": True,
                "max_retries": 2,
                "strategy": "Inject validation feedback into prompt",
            },
            LLMErrorType.RATE_LIMIT: {
                "should_retry": True,
                "max_retries": 3,
                "strategy": "Exponential backoff + switch provider",
            },
            LLMErrorType.TIMEOUT: {
                "should_retry": True,
                "max_retries": 2,
                "strategy": "Increase timeout, retry same provider",
            },
            LLMErrorType.CONTEXT_OVERFLOW: {
                "should_retry": True,
                "max_retries": 1,
                "strategy": "Truncate knowledge chunks, retry with shorter context",
            },
            LLMErrorType.PROVIDER_ERROR: {
                "should_retry": True,
                "max_retries": 3,
                "strategy": "Switch to next provider in fallback chain",
            },
            LLMErrorType.UNKNOWN: {
                "should_retry": True,
                "max_retries": 1,
                "strategy": "Generic retry, log for investigation",
            },
        }
        return strategies.get(error_type, strategies[LLMErrorType.UNKNOWN])
