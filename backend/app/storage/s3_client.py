"""Object-storage access: a thin, mockable facade every caller goes through.

Two backends, selected by `settings.STORAGE_BACKEND`:

- `"s3"` (default): boto3 against any S3-compatible endpoint — MinIO in
  local dev, Cloudflare R2 in production. Same API surface, only
  `settings.S3_ENDPOINT_URL` / credentials differ.
- `"local"`: plain files under `settings.STORAGE_LOCAL_DIR/<bucket>/<key>`.
  Exists so the full upload → process → publish flow runs with zero
  external services (no Docker, no MinIO) — dev/demo convenience only,
  never production: no durability story, no access control beyond file
  permissions.

Callers never touch `boto3` or the filesystem directly; go through the
functions here so backend dispatch, client construction, and error handling
stay in one place and are easy to mock in tests.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import ClientError

from app.config import REPO_ROOT, settings


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


def _local_path(bucket: str, key: str) -> Path:
    """Resolve `bucket/key` under the local storage root, refusing any key
    that escapes its bucket directory (matching S3 semantics, where a key
    can never reach outside its bucket). Keys are server-generated today,
    but the containment check keeps a future caller bug (or a hostile
    filename reaching a key) from turning into path traversal."""
    root = Path(settings.STORAGE_LOCAL_DIR)
    if not root.is_absolute():
        root = REPO_ROOT / root
    bucket_dir = (root / bucket).resolve()
    path = (bucket_dir / key).resolve()
    if not path.is_relative_to(bucket_dir):
        raise ValueError(f"Storage key escapes its bucket: {key!r}")
    return path


def upload_bytes(
    bucket: str,
    key: str,
    data: bytes,
    content_type: str | None = None,
    client: BaseClient | None = None,
) -> None:
    """Upload raw bytes to `bucket/key`."""
    if settings.STORAGE_BACKEND == "local":
        path = _local_path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return
    s3 = client or get_s3_client()
    extra_args: dict[str, Any] = {}
    if content_type:
        extra_args["ContentType"] = content_type
    s3.put_object(Bucket=bucket, Key=key, Body=data, **extra_args)


def download_bytes(bucket: str, key: str, client: BaseClient | None = None) -> bytes:
    """Download and return the full object body as bytes."""
    if settings.STORAGE_BACKEND == "local":
        return _local_path(bucket, key).read_bytes()
    s3 = client or get_s3_client()
    response = s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def generate_presigned_get(
    bucket: str, key: str, ttl: int = 3600, client: BaseClient | None = None
) -> str | None:
    """A time-limited GET URL for `bucket/key`, or `None` on the `local`
    backend (which has no HTTP surface).

    Not wired into any response yet — the API's own `/file` route stays the
    portable read path. This exists for a later optimization where large
    objects (e.g. Finding images) are served straight from object storage.
    """
    if settings.STORAGE_BACKEND == "local":
        return None
    s3 = client or get_s3_client()
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl
    )


def object_exists(bucket: str, key: str, client: BaseClient | None = None) -> bool:
    """Return True if `bucket/key` exists, False on a 404/NoSuchKey."""
    if settings.STORAGE_BACKEND == "local":
        return _local_path(bucket, key).is_file()
    s3 = client or get_s3_client()
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        if error_code in ("404", "NoSuchKey"):
            return False
        raise
