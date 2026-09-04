"""Raw file upload + display-name suggestion endpoints. Mounted at prefix
`/raw-files`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.config import settings
from app.db.session import get_db
from app.llm import LLMError, complete_json
from app.llm_credentials import llm_available_for, resolve_for_user
from app.logging_config import log_event
from app.models.enums import IngestionStatus, Modality, UploadStatus
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.models.user import User
from app.ratelimit import rate_limit_llm_consult, rate_limit_uploads
from app.security.file_validation import validate_upload_content, validate_upload_size
from app.storage.s3_client import object_exists, upload_bytes

router = APIRouter(prefix="/raw-files", tags=["raw-files"])
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def upload_raw_file(
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
    filename = Path(file.filename or "upload").name or "upload"

    # A stable, server-controlled key makes retries safe: an interrupted
    # request can upload the same content again without creating another
    # object, and the DB's direct-upload dedupe key returns the existing job.
    storage_key = f"raw/{user.id}/{content_hash}/source"
    existing = (
        db.query(RawFile)
        .filter(RawFile.owner_id == user.id, RawFile.dedupe_hash == content_hash)
        .one_or_none()
    )
    if existing is not None:
        existing_job = (
            db.query(IngestionJob)
            .filter(IngestionJob.raw_file_id == existing.id)
            .one_or_none()
        )
        if existing_job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Existing upload is missing its ingestion job; contact support with the raw file ID.",
            )
        return {
            "raw_file_id": existing.id,
            "ingestion_job_id": existing_job.id,
            "deduplicated": True,
        }

    if not object_exists(settings.S3_BUCKET_RAW, storage_key):
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
        dedupe_hash=content_hash,
        storage_version=f"sha256:{content_hash}",
        file_size_bytes=len(raw_bytes),
        vendor_format=None,
        upload_status=UploadStatus.uploaded,
    )
    try:
        db.add(raw_file)
        db.flush()
        ingestion_job = IngestionJob(
            raw_file_id=raw_file.id,
            status=IngestionStatus.pending,
        )
        db.add(ingestion_job)
        db.commit()
    except IntegrityError:
        # Concurrent retries can race after the object is safely uploaded. The
        # unique direct-upload key lets the loser recover the canonical job.
        db.rollback()
        existing = (
            db.query(RawFile)
            .filter(RawFile.owner_id == user.id, RawFile.dedupe_hash == content_hash)
            .one_or_none()
        )
        if existing is None:
            raise
        existing_job = db.query(IngestionJob).filter(IngestionJob.raw_file_id == existing.id).one()
        return {
            "raw_file_id": existing.id,
            "ingestion_job_id": existing_job.id,
            "deduplicated": True,
        }
    db.refresh(raw_file)
    db.refresh(ingestion_job)

    log_event(
        logger,
        "raw_file.upload.accepted",
        raw_file_id=str(raw_file.id),
        ingestion_job_id=str(ingestion_job.id),
        user_id=str(user.id),
        size_bytes=raw_file.file_size_bytes,
    )

    return {"raw_file_id": raw_file.id, "ingestion_job_id": ingestion_job.id, "deduplicated": False}


# --- Display-name suggestion ----------------------------------------------

_NAME_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": (
                "A short, human-readable display name for the spectrum — at most "
                "60 characters. Name what was measured and under what conditions, "
                "e.g. 'Polystyrene reference 785 nm'. Not a filename: no path and "
                "no extension. Letters, digits, spaces, dashes, underscores, "
                "periods and parentheses only."
            ),
        }
    },
    "required": ["title"],
}

#: A display name, not a filename — spaces and parentheses are the whole point.
_SAFE_TITLE_RE = re.compile(r"^[A-Za-z0-9 ._\-()]{1,80}$")


@router.post("/{raw_file_id}/name-suggestion")
async def suggest_name(
    raw_file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(rate_limit_llm_consult),
) -> dict:
    """Suggest a short display name for a raw file, from its extracted metadata.

    Advisory only: it returns a single validated string and never renames
    anything itself. Naming is a convenience on top of an upload, so it degrades
    to ``suggested_title: null`` rather than failing — an unreachable model or an
    unusable reply must never block someone from importing their data.
    """
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

    if not llm_available_for(db, user.id):
        return {
            "suggested_title": None,
            "reason": "No language model is configured for your account.",
        }

    try:
        result = await complete_json(
            system=(
                "Suggest a short, human-readable display name for a Raman "
                "spectroscopy record, based on its extracted metadata and the "
                "name of the file it came from. Name the sample and the notable "
                "acquisition conditions. Keep it under 60 characters. This is a "
                "label a scientist will read in a list, not a filename."
            ),
            # The filename carries signal the parsed header often lacks — sample
            # IDs, dates, the laser line — so the model sees both.
            user=(
                f"Original filename: {raw_file.original_filename or 'unknown'}\n\n"
                f"Metadata:\n\n{json.dumps(metadata, default=str)}"
            ),
            schema=_NAME_TOOL_SCHEMA,
            # Reasoning models bill their chain of thought against this budget;
            # 256 truncates before the name is even emitted.
            max_tokens=1024,
            credential=resolve_for_user(db, user.id),
        )
    except LLMError as exc:
        logger.info("name suggestion unavailable for raw_file=%s: %s", raw_file_id, exc)
        return {
            "suggested_title": None,
            "reason": "The naming model could not be reached.",
        }

    candidate = result.get("title")
    if isinstance(candidate, str) and _SAFE_TITLE_RE.match(candidate.strip()):
        return {"suggested_title": candidate.strip(), "reason": None}

    return {
        "suggested_title": None,
        "reason": "The model did not return a usable name.",
    }
