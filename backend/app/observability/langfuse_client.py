"""LangFuse client singleton for observability.

Instantiated once at module load when LANGFUSE_ENABLED=true.
Gracefully no-ops when keys are absent or langfuse is not installed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

# Module-level singleton — initialized once, reused everywhere
_langfuse: Optional[Any] = None
_initialized: bool = False


def _init_langfuse() -> Optional[Any]:
    """
    Initialize LangFuse client using settings from config.
    Safe to call multiple times — returns cached instance after first init.
    Returns None if:
      - LANGFUSE_ENABLED is False
      - credentials are missing
      - langfuse package is not installed
    """
    global _langfuse, _initialized

    if _initialized:
        return _langfuse

    _initialized = True

    try:
        from app.core.config import get_settings
        settings = get_settings()

        if not settings.LANGFUSE_ENABLED:
            logger.debug("LangFuse disabled via LANGFUSE_ENABLED=false")
            return None

        if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
            logger.warning(
                "LangFuse credentials not set (LANGFUSE_PUBLIC_KEY / "
                "LANGFUSE_SECRET_KEY). Tracing disabled."
            )
            return None

        from langfuse import Langfuse as LF
        _langfuse = LF(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        logger.info("LangFuse client initialized")
        return _langfuse

    except ImportError:
        logger.warning("langfuse package not installed — tracing disabled")
        return None
    except Exception as e:
        logger.warning(f"Failed to initialize LangFuse: {e}")
        return None


def get_langfuse() -> Optional[Any]:
    """Get the LangFuse client instance (lazy, cached)."""
    if _langfuse is None and not _initialized:
        _init_langfuse()
    return _langfuse


def flush_langfuse() -> None:
    """Flush pending LangFuse events (call on shutdown)."""
    global _langfuse
    if _langfuse is not None:
        try:
            _langfuse.flush()
        except Exception as e:
            logger.warning(f"LangFuse flush failed: {e}")
