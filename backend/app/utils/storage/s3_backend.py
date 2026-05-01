"""AWS S3 storage backend — kept as fallback when STORAGE_BACKEND=s3."""

import logging

import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.utils.storage.base import BaseStorage, StorageError

logger = logging.getLogger(__name__)


class S3Storage(BaseStorage):
    """Storage backend backed by AWS S3."""

    def __init__(self) -> None:
        self._client = None
        s = get_settings()
        self._bucket = s.S3_BUCKET_NAME
        self._region = s.AWS_REGION
        self._access_key = s.AWS_ACCESS_KEY_ID
        self._secret_key = s.AWS_SECRET_ACCESS_KEY
        self._ttl = s.S3_PRESIGNED_URL_TTL

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                region_name=self._region,
            )
        return self._client

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        file_type: str = "pdf",
    ) -> str:
        key = self._make_object_key(filename, user_id)
        try:
            self._get_client().put_object(
                Bucket=self._bucket,
                Key=key,
                Body=file_bytes,
                ContentType=self.get_file_content_type(filename),
                Metadata={"original_filename": filename, "user_id": user_id},
            )
            logger.info("S3 upload OK → %s", key)
            return key
        except ClientError as e:
            raise StorageError(f"S3 upload failed: {e}") from e

    async def download_file(self, object_key: str) -> bytes:
        try:
            resp = self._get_client().get_object(Bucket=self._bucket, Key=object_key)
            return resp["Body"].read()
        except ClientError as e:
            raise StorageError(f"S3 download failed: {e}") from e

    async def delete_file(self, object_key: str) -> None:
        try:
            self._get_client().delete_object(Bucket=self._bucket, Key=object_key)
        except ClientError:
            pass

    def generate_presigned_url(self, object_key: str, ttl_seconds: int | None = None) -> str:
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        try:
            return self._get_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=ttl,
            )
        except ClientError as e:
            raise StorageError(f"S3 presigned URL failed: {e}") from e

    def generate_upload_presigned_url(
        self,
        object_key: str,
        content_type: str = "application/pdf",
        ttl_seconds: int = 3600,
    ) -> str:
        try:
            return self._get_client().generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": object_key, "ContentType": content_type},
                ExpiresIn=ttl_seconds,
            )
        except ClientError as e:
            raise StorageError(f"S3 upload presigned URL failed: {e}") from e
