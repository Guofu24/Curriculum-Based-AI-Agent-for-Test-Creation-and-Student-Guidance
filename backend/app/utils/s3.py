"""
DEPRECATED — backward-compat shim for app.utils.s3.

All new code should use `app.utils.storage.get_storage()` directly.
This module forwards calls to the active storage backend so that any
remaining internal references (Celery tasks, tests, etc.) keep working
without modification.
"""

from app.utils.storage import get_storage
from app.utils.storage.base import StorageError

# Re-export StorageError under the old name for backward compat
S3Error = StorageError


async def upload_file(
    file_bytes: bytes,
    filename: str,
    user_id: str,
    file_type: str = "pdf",
) -> str:
    return await get_storage().upload_file(file_bytes, filename, user_id, file_type)


async def download_file(object_key: str) -> bytes:
    return await get_storage().download_file(object_key)


async def delete_file(object_key: str) -> None:
    await get_storage().delete_file(object_key)


def generate_presigned_url(object_key: str, ttl_seconds: int | None = None) -> str:
    return get_storage().generate_presigned_url(object_key, ttl_seconds)


def generate_fresh_url(object_key: str, ttl: int = 3600) -> str:
    return get_storage().generate_presigned_url(object_key, ttl)


def generate_upload_presigned_url(
    object_key: str,
    content_type: str = "application/pdf",
    ttl_seconds: int = 3600,
) -> str:
    return get_storage().generate_upload_presigned_url(object_key, content_type, ttl_seconds)


# Legacy sync aliases kept for any old code paths
async def upload_file_to_s3(
    file_content: bytes,
    original_filename: str,
    user_id: str,
    content_type: str = "application/pdf",
) -> str:
    return await get_storage().upload_file(file_content, original_filename, user_id)


async def delete_file_from_s3(object_key: str) -> bool:
    await get_storage().delete_file(object_key)
    return True


async def download_file_from_s3(object_key: str) -> bytes:
    return await get_storage().download_file(object_key)


def get_file_content_type(filename: str) -> str:
    return get_storage().get_file_content_type(filename)
