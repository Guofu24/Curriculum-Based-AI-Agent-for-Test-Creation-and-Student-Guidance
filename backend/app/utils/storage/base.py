"""Abstract base class for storage backends."""

import uuid
from abc import ABC, abstractmethod


class StorageError(Exception):
    """Generic storage operation error."""
    pass


class BaseStorage(ABC):
    """
    Abstract storage backend interface.
    All backends (MinIO, S3) implement this — callers never depend on a concrete class.
    """

    @abstractmethod
    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        file_type: str = "pdf",
    ) -> str:
        """Upload a file. Returns the object key (storage path)."""
        ...

    @abstractmethod
    async def download_file(self, object_key: str) -> bytes:
        """Download file content by object key."""
        ...

    @abstractmethod
    async def delete_file(self, object_key: str) -> None:
        """Delete a file. Silently ignores if not found."""
        ...

    @abstractmethod
    def generate_presigned_url(self, object_key: str, ttl_seconds: int | None = None) -> str:
        """Generate a presigned download URL."""
        ...

    @abstractmethod
    def generate_upload_presigned_url(
        self,
        object_key: str,
        content_type: str = "application/pdf",
        ttl_seconds: int = 3600,
    ) -> str:
        """Generate a presigned PUT URL for direct client-side upload."""
        ...

    def get_file_content_type(self, filename: str) -> str:
        """Return MIME type from file extension."""
        ext_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "txt": "text/plain",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
        }
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext_map.get(ext, "application/octet-stream")

    def _make_object_key(self, filename: str, user_id: str) -> str:
        """Generate a unique object key."""
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        return f"uploads/{user_id}/{uuid.uuid4()}.{ext}"
