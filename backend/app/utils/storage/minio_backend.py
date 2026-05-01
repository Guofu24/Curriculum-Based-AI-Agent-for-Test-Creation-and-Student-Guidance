"""MinIO storage backend — S3-compatible, priority default.

Running locally at:
  API:      http://127.0.0.1:9000
  Console:  http://127.0.0.1:9001
  User:     minioadmin / minioadmin
"""

import logging
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.utils.storage.base import BaseStorage, StorageError

logger = logging.getLogger(__name__)


class MinIOStorage(BaseStorage):
    """
    Storage backend backed by MinIO (local or remote).
    Uses boto3 with S3-compatible API — endpoint_url points to MinIO server.
    Automatically creates the bucket on first use if it does not exist.
    """

    def __init__(self) -> None:
        self._client = None
        self._bucket_ensured = False
        s = get_settings()
        self._bucket = s.MINIO_BUCKET_NAME
        self._endpoint = s.MINIO_ENDPOINT_URL
        self._public_url = s.MINIO_PUBLIC_URL
        self._access_key = s.MINIO_ACCESS_KEY
        self._secret_key = s.MINIO_SECRET_KEY
        self._ttl = s.S3_PRESIGNED_URL_TTL

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                # MinIO ignores region, but boto3 requires a non-empty value
                region_name="us-east-1",
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def _ensure_bucket(self) -> None:
        """Create the bucket if it does not already exist."""
        if self._bucket_ensured:
            return
        client = self._get_client()
        try:
            client.head_bucket(Bucket=self._bucket)
            logger.info("MinIO bucket '%s' exists.", self._bucket)
        except ClientError as e:
            code = int(e.response["Error"]["Code"])
            if code == 404:
                client.create_bucket(Bucket=self._bucket)
                logger.info("MinIO bucket '%s' created.", self._bucket)
            else:
                raise StorageError(f"MinIO bucket check failed: {e}") from e
        self._bucket_ensured = True

    def _rewrite_url(self, url: str) -> str:
        """Replace internal endpoint with public URL in presigned links."""
        if self._public_url and self._public_url.rstrip("/") != self._endpoint.rstrip("/"):
            url = url.replace(self._endpoint, self._public_url, 1)
        return url

    # ── BaseStorage interface ─────────────────────────────────────────────────

    async def upload_file(
        self,
        file_bytes: bytes,
        filename: str,
        user_id: str,
        file_type: str = "pdf",
    ) -> str:
        self._ensure_bucket()
        key = self._make_object_key(filename, user_id)
        try:
            self._get_client().put_object(
                Bucket=self._bucket,
                Key=key,
                Body=file_bytes,
                ContentType=self.get_file_content_type(filename),
            Metadata={
                # S3 metadata only allows ASCII — percent-encode Unicode filenames (RFC 5987).
                # The original filename is stored in the DB; metadata is for tracing only.
                "original_filename": quote(filename, safe=" .-_"),
                "user_id": user_id,
            },
            )
            logger.info("MinIO upload OK → %s", key)
            return key
        except ClientError as e:
            raise StorageError(f"MinIO upload failed: {e}") from e

    async def download_file(self, object_key: str) -> bytes:
        try:
            resp = self._get_client().get_object(Bucket=self._bucket, Key=object_key)
            # Read into a bytes buffer, then close the response immediately.
            # Returning resp["Body"].read() directly lets the response close
            # while still alive — which can leave the underlying HTTP stream
            # in an undefined state for some boto3/botocore versions.
            body = resp["Body"]
            data = body.read()
            body.close()
            if hasattr(resp, "close"):
                resp.close()
            return data
        except ClientError as e:
            raise StorageError(f"MinIO download failed: {e}") from e

    async def delete_file(self, object_key: str) -> None:
        try:
            self._get_client().delete_object(Bucket=self._bucket, Key=object_key)
        except ClientError:
            pass  # silently ignore

    def generate_presigned_url(self, object_key: str, ttl_seconds: int | None = None) -> str:
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        try:
            url = self._get_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=ttl,
            )
            return self._rewrite_url(url)
        except ClientError as e:
            raise StorageError(f"MinIO presigned URL failed: {e}") from e

    def generate_upload_presigned_url(
        self,
        object_key: str,
        content_type: str = "application/pdf",
        ttl_seconds: int = 3600,
    ) -> str:
        try:
            url = self._get_client().generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": object_key, "ContentType": content_type},
                ExpiresIn=ttl_seconds,
            )
            return self._rewrite_url(url)
        except ClientError as e:
            raise StorageError(f"MinIO upload presigned URL failed: {e}") from e
