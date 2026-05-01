"""Re-export Settings from app.core.config for convenience.

Import path for Phase 2+:
    from app.config import Settings, get_settings

This module exists at app/config.py as required by the folder structure spec,
but the canonical implementation lives in app/core/config.py.
"""
from app.core.config import Settings, get_settings

__all__ = ["Settings", "get_settings"]
