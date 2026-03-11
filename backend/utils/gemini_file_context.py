"""
Gemini File Context Manager

Manages uploading textbook PDFs to Google Gemini Files API and caching
the file references to avoid redundant uploads.

Usage:
    manager = GeminiFileManager()
    gemini_file = manager.upload_or_get_cached("path/to/textbook.pdf")
    # Pass gemini_file to Gemini API calls as context attachment

Notes:
    - Files uploaded to Gemini auto-expire after 48 hours
    - Cache is in-memory (resets on server restart)
    - Only activated when LLM_PROVIDER=google and GEMINI_USE_FILE_API=True
"""

import os
import hashlib
import logging
import time
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Cache TTL: 47 hours (Gemini files expire after 48h, refresh before expiry)
CACHE_TTL_SECONDS = 47 * 3600


class GeminiFileManager:
    """Upload and cache textbook files for use with Gemini API."""

    _instance = None
    _cache: dict[str, dict] = {}  # file_hash -> {"file": genai.File, "uploaded_at": float}

    @classmethod
    def get_instance(cls) -> "GeminiFileManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_client(self):
        """Get the Google GenAI client."""
        from google import genai
        from config import settings

        return genai.Client(api_key=settings.GOOGLE_API_KEY)

    def _file_hash(self, file_path: str) -> str:
        """Compute a quick hash of file path + size + mtime for cache key."""
        stat = os.stat(file_path)
        key = f"{file_path}:{stat.st_size}:{stat.st_mtime}"
        return hashlib.md5(key.encode()).hexdigest()

    def upload_or_get_cached(self, file_path: str) -> Optional[Any]:
        """
        Upload a file to Gemini Files API, or return cached version.

        Returns the genai File object, or None if upload fails.
        """
        try:
            file_hash = self._file_hash(file_path)
            now = time.time()

            # Check cache
            if file_hash in self._cache:
                cached = self._cache[file_hash]
                age = now - cached["uploaded_at"]
                if age < CACHE_TTL_SECONDS:
                    logger.info(
                        f"[GEMINI FILE] Using cached file "
                        f"(age={age/3600:.1f}h): {Path(file_path).name}"
                    )
                    return cached["file"]
                else:
                    logger.info("[GEMINI FILE] Cache expired, re-uploading...")
                    del self._cache[file_hash]

            # Upload to Gemini
            client = self._get_client()
            logger.info(f"[GEMINI FILE] Uploading: {Path(file_path).name}")

            uploaded_file = client.files.upload(file=file_path)

            logger.info(
                f"[GEMINI FILE] Uploaded successfully: "
                f"name={uploaded_file.name}, "
                f"mime_type={uploaded_file.mime_type}"
            )

            # Cache the result
            self._cache[file_hash] = {
                "file": uploaded_file,
                "uploaded_at": now,
            }

            return uploaded_file

        except Exception as e:
            logger.warning(
                f"[GEMINI FILE] Upload failed: {e}. "
                f"Falling back to text-only context."
            )
            return None

    def clear_cache(self):
        """Clear the file upload cache."""
        self._cache.clear()
        logger.info("[GEMINI FILE] Cache cleared.")
