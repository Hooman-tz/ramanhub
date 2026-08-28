"""Ingestion job read/confirm endpoints. Mounted at prefix `/ingestion-jobs`."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.ingestion.sanity_check import check as run_sanity_check
from app.models.enums import IngestionStatus, SpectrumState
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.schemas.ingestion import ConfirmMetadataRequest, IngestionJobOut

router = APIRouter(prefix="/ingestion-jobs", tags=["ingestion-jobs"])


def _get_owned_job(db: Session, job_id: str, user: User) -> IngestionJob:
    """Load the job and verify ownership via its raw file. Raises 404 (never
    403) on any mismatch so we don't leak whether the job exists."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    job = db.get(IngestionJob, job_uuid)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    raw_file = db.get(RawFile, job.raw_file_id)
    if raw_file is None or raw_file.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return job


@router.get("/{job_id}", response_model=IngestionJobOut)
def get_ingestion_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestionJob:
    return _get_owned_job(db, job_id, user)


@router.patch("/{job_id}", response_model=IngestionJobOut)
def confirm_ingestion_job_metadata(
    job_id: str,
    body: ConfirmMetadataRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestionJob:
    """Confirm metadata and atomically create (or recover) its private draft."""
    job = _get_owned_job(db, job_id, user)
    # Serializes all confirmation attempts for this ingestion record. The
    # unique raw_file_id constraint on Spectrum is the database backstop.
    job = (
        db.query(IngestionJob)
        .filter(IngestionJob.id == job.id)
        .with_for_update()
        .one()
    )
    if job.status != IngestionStatus.succeeded:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Metadata can be confirmed only after ingestion succeeds.",
        )
    metadata = body.metadata

    # Array/canonicalization flags are generated from the immutable raw bytes
    # by the worker, while field flags are recalculated for each user edit.
    flags = {
        key: value
        for key, value in (job.sanity_check_flags or {}).items()
        if key.startswith("array.")
        or key == "array"
    }
    flags.update(run_sanity_check(metadata, metadata.modality, db))
    job.extracted_metadata_confirmed = metadata.model_dump(mode="json")
    job.sanity_check_flags = flags
    job.confirmed_at = datetime.now(UTC)

    raw_file = db.get(RawFile, job.raw_file_id)
    if raw_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw file not found")
    draft = db.query(Spectrum).filter(Spectrum.raw_file_id == raw_file.id).one_or_none()
    if draft is None:
        draft = Spectrum(
            raw_file_id=raw_file.id,
            owner_id=user.id,
            modality=raw_file.modality,
            confirmed_metadata=job.extracted_metadata_confirmed,
            quality_flags=flags,
            canonicalization_version=job.canonicalization_version,
            state=SpectrumState.draft,
        )
        db.add(draft)
        db.flush()
    else:
        # Reconfirming a draft is recoverable/idempotent and keeps its
        # user-entered title, description, and processing work intact.
        draft.confirmed_metadata = job.extracted_metadata_confirmed
        draft.quality_flags = flags
        draft.canonicalization_version = job.canonicalization_version
        db.add(draft)
    job.draft_spectrum_id = draft.id
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/retry", response_model=IngestionJobOut)
def retry_ingestion_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestionJob:
    """Requeue an actionable failed ingestion without duplicating the raw file."""
    job = _get_owned_job(db, job_id, user)
    if job.status == IngestionStatus.succeeded:
        return job
    if job.status == IngestionStatus.running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ingestion is already running.")
    job.status = IngestionStatus.pending
    job.attempt_count = 0
    job.run_after = datetime.now(UTC)
    job.lease_expires_at = None
    job.error_message = None
    job.finished_at = None
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
