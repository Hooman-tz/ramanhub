"""Ingestion job read/confirm endpoints. Mounted at prefix `/ingestion-jobs`."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.ingestion.sanity_check import check as run_sanity_check
from app.ingestion.structure import (
    build_preview,
    compute_structure_hash,
    store_layout,
    verify_layout,
)
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum
from app.models.enums import IngestionStatus, SpectrumState, UploadStatus
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.schemas.ingestion import (
    ConfirmMetadataRequest,
    DeclareLayoutRequest,
    FileLayout,
    IngestionJobOut,
)
from app.storage.s3_client import download_bytes

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
    drafts = _sync_drafts(db, job, raw_file, user, flags)
    job.draft_spectrum_id = drafts[0].id
    if len(drafts) > 1:
        job.draft_dataset_id = _group_into_dataset(db, job, raw_file, user, drafts).id
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _trace_specs(job: IngestionJob) -> list[tuple[int | None, str | None]]:
    """The `(trace index, label)` pairs this file should become drafts for.

    A job with no stored layout predates structure detection and yields a
    single untraced draft, exactly as before — `source_trace_index IS NULL`
    is what every existing spectrum carries.
    """
    if not job.file_layout:
        return [(None, None)]
    try:
        layout = FileLayout.model_validate(job.file_layout)
    except ValueError:
        return [(None, None)]
    if not layout.traces:
        return [(None, None)]
    return [(trace.index, trace.label) for trace in layout.traces]


def _sync_drafts(
    db: Session,
    job: IngestionJob,
    raw_file: RawFile,
    user: User,
    flags: dict,
) -> list[Spectrum]:
    """Create (or refresh) one private draft per trace in the file.

    Reconfirming is idempotent per `(raw_file_id, source_trace_index)` and
    keeps each draft's user-entered title, description, and processing work
    intact — the same guarantee the single-draft path always gave, now held
    per trace.
    """
    existing = {
        spectrum.source_trace_index: spectrum
        for spectrum in db.query(Spectrum).filter(Spectrum.raw_file_id == raw_file.id).all()
    }
    drafts: list[Spectrum] = []
    for trace_index, label in _trace_specs(job):
        draft = existing.get(trace_index)
        if draft is None and trace_index is not None and None in existing:
            # This file was ingested before layout detection and already has
            # its untraced draft. Adopt it as the first trace rather than
            # creating a duplicate spectrum of the same data.
            draft = existing.pop(None)
            draft.source_trace_index = trace_index
        if draft is None:
            draft = Spectrum(
                raw_file_id=raw_file.id,
                owner_id=user.id,
                modality=raw_file.modality,
                source_trace_index=trace_index,
                source_trace_label=label,
                title=label,
                state=SpectrumState.draft,
            )
            db.add(draft)
        draft.source_trace_label = label
        draft.confirmed_metadata = job.extracted_metadata_confirmed
        draft.quality_flags = flags
        draft.canonicalization_version = job.canonicalization_version
        db.add(draft)
        drafts.append(draft)
    db.flush()
    return drafts


def _group_into_dataset(
    db: Session,
    job: IngestionJob,
    raw_file: RawFile,
    user: User,
    drafts: list[Spectrum],
) -> AnalysisDataset:
    """Put a multi-spectrum file's drafts in one dataset.

    A file that holds eight spectra is one experiment, and its spectra are
    only useful together; the dataset is how the rest of the app already
    expresses that.
    """
    dataset = db.get(AnalysisDataset, job.draft_dataset_id) if job.draft_dataset_id else None
    if dataset is None:
        name = _unique_dataset_name(db, user, raw_file.original_filename or "Uploaded spectra")
        dataset = AnalysisDataset(
            owner_id=user.id,
            modality=raw_file.modality,
            name=name,
            description=(
                f"{len(drafts)} spectra read from {raw_file.original_filename}."
                if raw_file.original_filename
                else f"{len(drafts)} spectra read from one upload."
            ),
        )
        db.add(dataset)
        db.flush()
    present = {
        row.spectrum_id
        for row in db.query(AnalysisDatasetSpectrum)
        .filter(AnalysisDatasetSpectrum.dataset_id == dataset.id)
        .all()
    }
    for position, draft in enumerate(drafts):
        if draft.id not in present:
            db.add(
                AnalysisDatasetSpectrum(
                    dataset_id=dataset.id, spectrum_id=draft.id, position=position
                )
            )
    return dataset


def _unique_dataset_name(db: Session, user: User, base: str) -> str:
    """Dataset names are unique per owner, and a scientist re-uploading a
    file with the same name should not get a 500 for it."""
    stem = base.rsplit(".", 1)[0][:140] or "Uploaded spectra"
    name = stem
    for suffix in range(2, 100):
        taken = (
            db.query(AnalysisDataset)
            .filter(AnalysisDataset.owner_id == user.id, AnalysisDataset.name == name)
            .first()
        )
        if taken is None:
            return name
        name = f"{stem} ({suffix})"
    return f"{stem} ({uuid.uuid4().hex[:6]})"


@router.post("/{job_id}/layout", response_model=IngestionJobOut)
def declare_ingestion_job_layout(
    job_id: str,
    body: DeclareLayoutRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IngestionJob:
    """Let the owner say how their file is laid out, when detection could not.

    The declaration is checked against the real bytes before it is accepted —
    a person can mistype a column index just as easily as a model can guess
    one wrong, and a layout that cannot produce a spectrum is rejected with a
    422 they can act on rather than stored and discovered later.

    An accepted layout is cached under the file's structure signature, so the
    next upload of this format is read correctly without asking again.
    """
    job = _get_owned_job(db, job_id, user)
    if job.confirmed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload has already been confirmed; edit its spectra instead.",
        )
    if job.status not in (IngestionStatus.needs_input, IngestionStatus.succeeded):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A layout can only be declared once ingestion has read the file.",
        )
    raw_file = db.get(RawFile, job.raw_file_id)
    if raw_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw file not found")

    layout = body.layout.model_copy(update={"source": "user", "confidence": 1.0})
    raw_bytes = download_bytes(raw_file.storage_bucket, raw_file.storage_key)
    if not verify_layout(raw_bytes, layout):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "That layout doesn't produce a readable spectrum from this file. "
                "Check which column holds the wavenumbers and which hold intensities."
            ),
        )

    preview = build_preview(raw_bytes)
    store_layout(db, compute_structure_hash(preview), layout)

    job.file_layout = layout.model_dump(mode="json")
    job.structure_preview = preview.model_dump(mode="json")
    job.layout_source = "user"
    job.error_message = None
    if job.status == IngestionStatus.needs_input:
        job.status = IngestionStatus.succeeded
        job.finished_at = datetime.now(UTC)
    db.add(job)
    db.query(RawFile).filter(RawFile.id == raw_file.id).update(
        {RawFile.upload_status: UploadStatus.parsed}, synchronize_session=False
    )
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
