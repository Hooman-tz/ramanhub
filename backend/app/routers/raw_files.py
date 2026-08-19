"""Raw file upload + rename-suggestion endpoints. Mounted at prefix
`/raw-files`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid

import anthropic
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.config import settings
from app.db.session import get_db
from app.ingestion.jobs import enqueue_ingestion_job
from app.logging_config import log_event
from app.models.enums import IngestionStatus, Modality, UploadStatus
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.models.user import User
from app.ratelimit import rate_limit_uploads
from app.security.file_validation import validate_upload_content, validate_upload_size
from app.storage.s3_client import upload_bytes

router = APIRouter(prefix="/raw-files", tags=["raw-files"])
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_raw_file(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(rate_limit_uploads),
) -> dict:
    raw_bytes = await file.read()

    # Content-based validation (never trust the filename/extension) — see
    # app/security/file_validation.py. Size is checked first since it's the
    # cheapest possible rejection.
    validate_upload_size(len(raw_bytes))
    validate_upload_content(raw_bytes)

    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    filename = file.filename or "upload"
    storage_key = f"{user.id}/{content_hash}/{filename}"

    upload_bytes(
        bucket=settings.S3_BUCKET_RAW,
        key=storage_key,
        data=raw_bytes,
        content_type=file.content_type,
    )

    raw_file = RawFile(
        owner_id=user.id,
        modality=Modality.raman,
        storage_bucket=settings.S3_BUCKET_RAW,
        storage_key=storage_key,
        original_filename=filename,
        content_hash=content_hash,
        file_size_bytes=len(raw_bytes),
        vendor_format=None,
        upload_status=UploadStatus.uploaded,
    )
    db.add(raw_file)
    db.flush()

    ingestion_job = IngestionJob(
        raw_file_id=raw_file.id,
        status=IngestionStatus.pending,
    )
    db.add(ingestion_job)
    db.commit()
    db.refresh(raw_file)
    db.refresh(ingestion_job)

    enqueue_ingestion_job(background_tasks, raw_file.id)

    log_event(
        logger,
        "raw_file.upload.accepted",
        raw_file_id=str(raw_file.id),
        ingestion_job_id=str(ingestion_job.id),
        user_id=str(user.id),
        size_bytes=raw_file.file_size_bytes,
    )

    return {"raw_file_id": raw_file.id, "ingestion_job_id": ingestion_job.id}


# --- Rename suggestion -------------------------------------------------

_RENAME_TOOL_NAME = "suggest_filename"

_RENAME_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "filename": {
            "type": "string",
            "description": (
                "A single suggested filename (no path, no extension change), "
                "using only letters, digits, dashes, and underscores."
            ),
        }
    },
    "required": ["filename"],
}

_SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


@router.post("/{raw_file_id}/rename-suggestion")
async def suggest_rename(
    raw_file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Suggest a filename based on a raw file's extracted metadata. This is
    advisory only — it returns a single validated string and never renames
    anything itself."""
    try:
        raw_file_uuid = uuid.UUID(raw_file_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    raw_file = db.get(RawFile, raw_file_uuid)
    if raw_file is None or raw_file.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    job = (
        db.query(IngestionJob)
        .filter(IngestionJob.raw_file_id == raw_file.id)
        .order_by(IngestionJob.created_at.desc())
        .first()
    )
    metadata = (job.extracted_metadata_confirmed or job.extracted_metadata_raw) if job else None
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No extracted metadata available yet for this file",
        )

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        message = await client.messages.create(
            model="claude-sonnet-5",
            max_tokens=256,
            system=(
                "Suggest a short, descriptive filename (no extension) for a Raman "
                "spectroscopy data file, based on its extracted metadata. Call the "
                f"`{_RENAME_TOOL_NAME}` tool exactly once."
            ),
            tools=[
                {
                    "name": _RENAME_TOOL_NAME,
                    "description": "Record the suggested filename.",
                    "input_schema": _RENAME_TOOL_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": _RENAME_TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": f"Metadata:\n\n{json.dumps(metadata, default=str)}",
                }
            ],
        )
    except anthropic.APIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Rename suggestion failed: {exc}"
        ) from exc

    suggestion: str | None = None
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _RENAME_TOOL_NAME:
            candidate = block.input.get("filename")
            if isinstance(candidate, str) and _SAFE_FILENAME_RE.match(candidate):
                suggestion = candidate
            break

    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Model did not return a usable filename suggestion",
        )

    return {"suggested_filename": suggestion}
