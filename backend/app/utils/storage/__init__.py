"""
Storage package — unified abstraction over MinIO and AWS S3.

Usage:
    from app.utils.storage import get_storage, StorageError

    storage = get_storage()
    key = await storage.upload_file(...)
    data = await storage.download_file(key)

Backend is selected via STORAGE_BACKEND env var:
  "minio"  (default) → MinIOStorage  — points to local MinIO server
  "s3"               → S3Storage     — points to AWS S3
"""

import logging

from app.utils.storage.base import BaseStorage, StorageError  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

_storage: BaseStorage | None = None


def get_storage() -> BaseStorage:
    """
    Return the singleton storage backend.
    Lazily initialised on first call based on STORAGE_BACKEND setting.
    Thread-/coroutine-safe for reads after the first call.
    """
    global _storage
    if _storage is not None:
        return _storage

    from app.core.config import get_settings
    settings = get_settings()
    backend = settings.STORAGE_BACKEND.lower().strip()

    if backend == "minio":
        from app.utils.storage.minio_backend import MinIOStorage
        _storage = MinIOStorage()
        logger.info("Storage backend: MinIO (%s)", settings.MINIO_ENDPOINT_URL)
    elif backend == "s3":
        from app.utils.storage.s3_backend import S3Storage
        _storage = S3Storage()
        logger.info("Storage backend: AWS S3 (bucket=%s)", settings.S3_BUCKET_NAME)
    else:
        raise ValueError(
            f"Unknown STORAGE_BACKEND='{backend}'. "
            "Supported values: 'minio' (default), 's3'."
        )

    return _storage
