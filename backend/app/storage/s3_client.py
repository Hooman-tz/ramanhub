"""Thin, mockable wrapper around a boto3 S3-compatible client.

Works against MinIO in local dev and Cloudflare R2 in production — same API
surface, only `settings.S3_ENDPOINT_URL` / credentials differ. Callers should
never touch `boto3` directly; go through the functions here so the client
construction and error handling stay in one place and are easy to mock in
tests.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import ClientError

from app.config import settings


@lru_cache(maxsize=1)
def get_s3_client() -> BaseClient:
    """Return a cached boto3 S3 client configured from `app.config.settings`."""
    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION,
        config=Config(signature_version="s3v4"),
    )


def upload_bytes(
    bucket: str,
    key: str,
    data: bytes,
    content_type: str | None = None,
    client: BaseClient | None = None,
) -> None:
    """Upload raw bytes to `bucket/key`."""
    s3 = client or get_s3_client()
    extra_args: dict[str, Any] = {}
    if content_type:
        extra_args["ContentType"] = content_type
    s3.put_object(Bucket=bucket, Key=key, Body=data, **extra_args)


def download_bytes(bucket: str, key: str, client: BaseClient | None = None) -> bytes:
    """Download and return the full object body as bytes."""
    s3 = client or get_s3_client()
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def object_exists(bucket: str, key: str, client: BaseClient | None = None) -> bool:
    """Return True if `bucket/key` exists, False on a 404/NoSuchKey."""
    s3 = client or get_s3_client()
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey"):
            return False
        raise
