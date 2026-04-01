"""AWS S3 utilities for secure file storage."""

import uuid
import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings

settings = get_settings()


class S3Error(Exception):
    """S3 operation error."""
    pass


def get_s3_client():
    """Get boto3 S3 client."""
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


async def upload_file_to_s3(
    file_content: bytes,
    original_filename: str,
    user_id: str,
    content_type: str = "application/pdf",
) -> str:
    """
    Upload a file to S3 private bucket.
    Returns the S3 key.
    """
    # Generate unique S3 key
    file_ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else ""
    unique_id = str(uuid.uuid4())
    s3_key = f"uploads/{user_id}/{unique_id}.{file_ext}"

    try:
        s3_client = get_s3_client()
        s3_client.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            Body=file_content,
            ContentType=content_type,
            # Private by default - no public access
            Metadata={
                "original_filename": original_filename,
                "user_id": user_id,
            }
        )
        return s3_key

    except ClientError as e:
        raise S3Error(f"Failed to upload file: {str(e)}")


def generate_presigned_url(s3_key: str, ttl_seconds: int | None = None) -> str:
    """
    Generate a presigned URL for downloading a file.
    URL expires after ttl_seconds (default from settings).
    """
    if ttl_seconds is None:
        ttl_seconds = settings.S3_PRESIGNED_URL_TTL

    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": s3_key,
            },
            ExpiresIn=ttl_seconds,
        )
        return url

    except ClientError as e:
        raise S3Error(f"Failed to generate presigned URL: {str(e)}")


def generate_fresh_url(s3_key: str, ttl: int = 3600) -> str:
    """
    Alias for generate_presigned_url, used for /refresh-url endpoint (G20).
    Generates a new presigned URL with fresh TTL.
    """
    return generate_presigned_url(s3_key, ttl_seconds=ttl)


def generate_upload_presigned_url(
    s3_key: str,
    content_type: str = "application/pdf",
    ttl_seconds: int = 3600,
) -> str:
    """
    Generate a presigned URL for uploading a file directly to S3.
    Used for large file uploads to avoid passing through backend.
    """
    try:
        s3_client = get_s3_client()
        url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": s3_key,
                "ContentType": content_type,
            },
            ExpiresIn=ttl_seconds,
        )
        return url

    except ClientError as e:
        raise S3Error(f"Failed to generate upload URL: {str(e)}")


async def delete_file_from_s3(s3_key: str) -> bool:
    """Delete a file from S3."""
    try:
        s3_client = get_s3_client()
        s3_client.delete_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
        )
        return True

    except ClientError:
        return False


async def download_file_from_s3(s3_key: str) -> bytes:
    """Download file content from S3."""
    try:
        s3_client = get_s3_client()
        response = s3_client.get_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
        )
        return response["Body"].read()

    except ClientError as e:
        raise S3Error(f"Failed to download file: {str(e)}")


# ── Spec-named aliases ─────────────────────────────────────────────────────────

async def upload_file(
    file_bytes: bytes,
    filename: str,
    user_id: str,
    file_type: str = "pdf",
) -> str:
    """
    Upload a file to S3 (spec naming).
    Returns the S3 key.
    """
    content_type = get_file_content_type(filename)
    return await upload_file_to_s3(
        file_content=file_bytes,
        original_filename=filename,
        user_id=user_id,
        content_type=content_type,
    )


async def download_file(s3_key: str) -> bytes:
    """Download file content from S3 (spec naming)."""
    return await download_file_from_s3(s3_key)


async def delete_file(s3_key: str) -> None:
    """Delete a file from S3 (spec naming)."""
    await delete_file_from_s3(s3_key)


def get_file_content_type(filename: str) -> str:
    """Get MIME content type from file extension."""
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
