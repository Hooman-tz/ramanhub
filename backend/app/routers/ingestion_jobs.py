"""Ingestion job read/confirm endpoints. Mounted at prefix `/ingestion-jobs`."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.ingestion.sanity_check import check as run_sanity_check
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
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
    """The only write path into `extracted_metadata_confirmed`. Re-runs the
    sanity check against the edited values and overwrites
    `sanity_check_flags` with the result."""
    job = _get_owned_job(db, job_id, user)
    metadata = body.metadata

    flags = run_sanity_check(metadata, metadata.modality, db)

    job.extracted_metadata_confirmed = metadata.model_dump(mode="json")
    job.sanity_check_flags = flags
    job.confirmed_at = datetime.now(UTC)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
