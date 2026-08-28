"""Spectrum CRUD-lite + publish/embargo lifecycle + fork endpoints.

Mounted with no prefix (paths below are the full route) — `/spectra`,
`/spectra/{spectrum_id}`, `/spectra/{spectrum_id}/publish`,
`/spectra/{spectrum_id}/release-embargo`, `/spectra/{spectrum_id}/fork`.
"""
from __future__ import annotations

import logging
import uuid as uuid_module
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user, get_current_user_optional
from app.db.session import get_db
from app.doi_lookup import lookup_doi, normalize_doi
from app.ingestion.sanity_check import check as run_sanity_check
from app.models.enums import IngestionStatus, SpectrumState
from app.models.ingestion_job import IngestionJob
from app.models.license import License
from app.models.processing_ledger import ProcessingLedger
from app.models.publication import Publication, PublicationSnapshot
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.cache import get_or_compute
from app.processing.state_machine import (
    effective_state,
    embargo,
    publish,
    release_embargo_early,
    require_owner_or_public,
)
from app.raman_contract import checksum_bytes
from app.schemas.ingestion import ExtractedMetadata
from app.schemas.ledger import Ledger, LedgerStep
from app.spectra_io import compute_snr, load_raw_spectrum
from app.spectrum_lifecycle import (
    ingestion_job_for_raw,
    publication_readiness,
    spectrum_provenance,
)
from app.storage.s3_client import download_bytes, upload_bytes

router = APIRouter(tags=["spectra"])
logger = logging.getLogger(__name__)


class SpectrumCreate(BaseModel):
    raw_file_id: UUID
    current_ledger_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    confirmed_metadata: dict | None = None
    # Module 4: owner-entered — no reliable extracted-metadata source for
    # "material type" in the current ingestion schema (see
    # app.schemas.ingestion.ExtractedMetadata), so it's user-supplied like
    # title/description rather than derived.
    material_type: str | None = None


class SpectrumUpdate(BaseModel):
    current_ledger_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    confirmed_metadata: dict | None = None
    material_type: str | None = None


class PublishRequest(BaseModel):
    license_id: str
    embargo_release_at: datetime | None = None
    # Module 4 trust-tier / Module 3 DOI-lookup integration seam: a non-empty
    # doi here marks the spectrum "DOI-verified" for the /search/spectra
    # trust_tier filter (see app.processing.state_machine.publish/embargo).
    doi: str | None = None


class SpectrumResponse(BaseModel):
    id: UUID
    raw_file_id: UUID
    modality: str
    title: str | None
    description: str | None
    confirmed_metadata: dict | None
    quality_flags: dict | None = None
    canonicalization_version: str | None = None
    parent_spectrum_id: UUID | None = None
    material_type: str | None
    current_ledger_id: UUID | None
    license_id: str | None
    state: str
    embargo_release_at: datetime | None
    published_at: datetime | None
    doi: str | None
    publication_id: UUID | None = None
    moderation_status: str = "visible"
    is_owner: bool = False
    created_at: datetime
    updated_at: datetime
    ledger_steps: list | None = None
    current_ledger: dict | None = None
    provenance: dict | None = None
    publish_readiness: dict | None = None

    model_config = {"from_attributes": True}


def _recompute_derived_fields(spectrum: Spectrum, db: Session) -> None:
    """Populate the denormalized Module 4 search fields
    (`excitation_wavelength_nm`, `snr`) from the spectrum's current
    metadata/processed array. `material_type` is owner-entered directly (see
    `SpectrumCreate`/`SpectrumUpdate` above), so it isn't touched here.

    Call sites (deliberately not a fully reactive system — see module spec):
    end of `create_spectrum`, end of `update_spectrum` (unconditionally;
    cheap enough not to bother tracking exactly which fields changed), and
    once more right before `publish`/`embargo` in `publish_spectrum`, so the
    fields `/search/spectra` filters on are fresh at the moment a spectrum
    becomes visible to the public commons.

    Best-effort: any failure while loading/computing the processed array
    (e.g. a raw file that doesn't parse) is swallowed rather than raised —
    derived-field computation must never block create/update/publish.
    """
    if spectrum.confirmed_metadata:
        laser_wavelength = spectrum.confirmed_metadata.get("laser_wavelength_nm")
        if laser_wavelength is not None:
            try:
                spectrum.excitation_wavelength_nm = float(laser_wavelength)
            except (TypeError, ValueError):
                pass

    try:
        ledger_row = (
            db.get(ProcessingLedger, spectrum.current_ledger_id)
            if spectrum.current_ledger_id is not None
            else None
        )
        if ledger_row is not None:
            ledger = Ledger(
                schema_version=ledger_row.schema_version,
                raw_file_id=ledger_row.raw_file_id,
                steps=[LedgerStep.model_validate(step) for step in ledger_row.steps],
            )
            _wavenumbers, intensities = get_or_compute(spectrum.raw_file_id, ledger, db)
        else:
            raw_file = db.get(RawFile, spectrum.raw_file_id)
            if raw_file is None:
                return
            _wavenumbers, intensities = load_raw_spectrum(raw_file)
    except Exception:  # noqa: BLE001 - derived-field computation must never block create/update/publish
        return

    spectrum.snr = compute_snr(intensities)


def _serialize(
    spectrum: Spectrum, db: Session, viewer: User | None = None
) -> SpectrumResponse:
    ledger_steps = None
    if spectrum.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, spectrum.current_ledger_id)
        if ledger_row is not None:
            ledger_steps = ledger_row.steps
    payload = SpectrumResponse.model_validate(spectrum)
    payload.state = effective_state(spectrum)
    payload.ledger_steps = ledger_steps
    payload.current_ledger = (
        {"id": str(ledger_row.id), "steps": ledger_row.steps}
        if spectrum.current_ledger_id is not None
        and (ledger_row := db.get(ProcessingLedger, spectrum.current_ledger_id)) is not None
        else None
    )
    payload.provenance = spectrum_provenance(spectrum, db)
    payload.publish_readiness = publication_readiness(spectrum, db)
    payload.is_owner = viewer is not None and spectrum.owner_id == viewer.id
    return payload


def _get_owned_spectrum_or_404(spectrum_id: UUID, user: User, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None or spectrum.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return spectrum


@router.post("/spectra", response_model=SpectrumResponse, status_code=status.HTTP_201_CREATED)
def create_spectrum(
    body: SpectrumCreate,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    raw_file = db.get(RawFile, body.raw_file_id)
    if raw_file is None or raw_file.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw file not found")

    job = ingestion_job_for_raw(raw_file.id, db)
    if (
        job is None
        or job.status != IngestionStatus.succeeded
        or job.extracted_metadata_confirmed is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Create a draft by confirming a completed ingestion job first.",
        )

    existing = db.query(Spectrum).filter(Spectrum.raw_file_id == raw_file.id).one_or_none()
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return _serialize(existing, db, user)

    if body.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, body.current_ledger_id)
        if ledger_row is None or ledger_row.raw_file_id != raw_file.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current_ledger_id does not reference a ledger for this raw file",
            )

    spectrum = Spectrum(
        raw_file_id=raw_file.id,
        owner_id=user.id,
        modality=raw_file.modality,
        title=body.title,
        description=body.description,
        confirmed_metadata=job.extracted_metadata_confirmed,
        quality_flags=job.sanity_check_flags,
        canonicalization_version=job.canonicalization_version,
        material_type=body.material_type,
        current_ledger_id=body.current_ledger_id,
        state=SpectrumState.draft,
    )
    _recompute_derived_fields(spectrum, db)
    db.add(spectrum)
    db.flush()
    job.draft_spectrum_id = spectrum.id
    db.add(job)
    db.commit()
    db.refresh(spectrum)
    return _serialize(spectrum, db, user)


@router.get("/spectra/{spectrum_id}", response_model=SpectrumResponse)
def get_spectrum(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> SpectrumResponse:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)
    return _serialize(spectrum, db, user)


@router.patch("/spectra/{spectrum_id}", response_model=SpectrumResponse)
def update_spectrum(
    spectrum_id: UUID,
    body: SpectrumUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    spectrum = _get_owned_spectrum_or_404(spectrum_id, user, db)
    if spectrum.state != SpectrumState.draft:
        raise HTTPException(status_code=400, detail="Only draft spectra can be edited")

    if body.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, body.current_ledger_id)
        if ledger_row is None or ledger_row.raw_file_id != spectrum.raw_file_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current_ledger_id does not reference a ledger for this raw file",
            )
        spectrum.current_ledger_id = body.current_ledger_id
    if body.title is not None:
        spectrum.title = body.title
    if body.description is not None:
        spectrum.description = body.description
    if body.confirmed_metadata is not None:
        try:
            confirmed = ExtractedMetadata.model_validate(body.confirmed_metadata)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Confirmed metadata does not satisfy the Raman profile: {exc}",
            ) from exc
        confirmed_metadata = confirmed.model_dump(mode="json")
        job = ingestion_job_for_raw(spectrum.raw_file_id, db)
        array_flags = {
            key: value
            for key, value in ((job.sanity_check_flags if job else spectrum.quality_flags) or {}).items()
            if key == "array" or key.startswith("array.")
        }
        array_flags.update(run_sanity_check(confirmed, confirmed.modality, db))
        spectrum.confirmed_metadata = confirmed_metadata
        spectrum.quality_flags = array_flags
        if job is not None:
            job.extracted_metadata_confirmed = confirmed_metadata
            job.sanity_check_flags = array_flags
            db.add(job)
    if body.material_type is not None:
        spectrum.material_type = body.material_type

    _recompute_derived_fields(spectrum, db)

    db.add(spectrum)
    db.commit()
    db.refresh(spectrum)
    return _serialize(spectrum, db, user)


@router.post("/spectra/{spectrum_id}/doi/verify", response_model=SpectrumResponse)
async def verify_spectrum_doi(
    spectrum_id: UUID,
    doi: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> SpectrumResponse:
    """Persist resolver-backed DOI evidence before a verified label is shown."""
    spectrum = _get_owned_spectrum_or_404(spectrum_id, user, db)
    if spectrum.state != SpectrumState.draft:
        raise HTTPException(status_code=400, detail="Only draft spectra can be updated")
    normalized = normalize_doi(doi)
    if normalized is None:
        raise HTTPException(status_code=422, detail="Enter a valid DOI.")
    metadata = await lookup_doi(normalized)
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The DOI could not be resolved through Crossref.",
        )
    snapshot = db.query(PublicationSnapshot).filter_by(spectrum_id=spectrum.id).one_or_none()
    if snapshot is None:
        snapshot = PublicationSnapshot(
            spectrum_id=spectrum.id,
            doi=normalized,
            provider="crossref",
            verification_status="verified",
            snapshot=metadata.model_dump(mode="json"),
            verified_at=datetime.now(UTC),
        )
    else:
        snapshot.doi = normalized
        snapshot.provider = "crossref"
        snapshot.verification_status = "verified"
        snapshot.snapshot = metadata.model_dump(mode="json")
        snapshot.verified_at = datetime.now(UTC)
    publication = db.query(Publication).filter(Publication.doi == normalized).one_or_none()
    if publication is None:
        publication = Publication(
            doi=normalized,
            provider="crossref",
            verification_status="verified",
            snapshot=metadata.model_dump(mode="json"),
            verified_at=datetime.now(UTC),
        )
        db.add(publication)
        db.flush()
    else:
        publication.provider = "crossref"
        publication.verification_status = "verified"
        publication.snapshot = metadata.model_dump(mode="json")
        publication.verified_at = datetime.now(UTC)
    spectrum.doi = normalized
    spectrum.publication_id = publication.id
    db.add_all([spectrum, snapshot, publication])
    db.commit()
    db.refresh(spectrum)
    return _serialize(spectrum, db, user)


@router.post("/spectra/{spectrum_id}/publish", response_model=SpectrumResponse)
def publish_spectrum(
    spectrum_id: UUID,
    body: PublishRequest,
    db: Session = Depends(get_db),
    # Publishing grants a license to the public commons — an identity-carrying
    # act, so guests are gated out (they keep drafts + the processing tools).
    user: User = Depends(get_current_full_user),
) -> SpectrumResponse:
    spectrum = _get_owned_spectrum_or_404(spectrum_id, user, db)
    _recompute_derived_fields(spectrum, db)
    if db.get(License, body.license_id) is None:
        raise HTTPException(status_code=422, detail="Choose a valid publication license.")
    if body.doi:
        normalized = normalize_doi(body.doi)
        if normalized is None or normalized != spectrum.doi:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Verify this DOI on the draft before publishing.",
            )
    readiness = publication_readiness(spectrum, db)
    if not readiness["ready"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Publication requirements are incomplete.",
                "blockers": readiness["blockers"],
                "warnings": readiness["warnings"],
            },
        )
    if body.embargo_release_at is not None:
        spectrum = embargo(spectrum, body.license_id, body.embargo_release_at, db, doi=spectrum.doi)
    else:
        spectrum = publish(spectrum, body.license_id, db, doi=spectrum.doi)
    return _serialize(spectrum, db, user)


@router.post(
    "/spectra/{spectrum_id}/fork",
    response_model=SpectrumResponse,
    status_code=status.HTTP_201_CREATED,
)
def fork_spectrum(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    # Guests may fork — experimenting with the processing tools on public
    # spectra is exactly the try-before-login loop. Publishing the fork is
    # what needs a full account, and that's gated separately.
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    """Copy a readable spectrum into the caller's own workspace as a new
    draft — the GitHub-for-data fork, literally. Processing pipelines can
    only be attached to raw files you own (see `create_ledger`'s ownership
    check), so this is how anyone experiments on a *public* spectrum: fork
    first, then process the copy freely.

    What's copied: the raw bytes (to a forker-scoped storage key — a real
    copy, so the fork's lifecycle is fully independent of the source),
    title/description/confirmed_metadata/material_type, and the source's
    current processing ledger, replayed onto the new raw file so the fork
    opens looking identical. What's NOT copied: publish state (forks start
    as drafts), license, DOI, and social signals — those belong to the
    source, not the copy.
    """
    source = db.get(Spectrum, spectrum_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # Drafts/embargoed spectra stay unforkable by anyone but their owner —
    # same visibility rule as every other read.
    require_owner_or_public(source, user)

    source_raw = db.get(RawFile, source.raw_file_id)
    if source_raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw file not found")

    raw_bytes = download_bytes(source_raw.storage_bucket, source_raw.storage_key)
    if checksum_bytes(raw_bytes) != source_raw.content_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source raw-object checksum does not match its immutable record.",
        )
    fork_key = f"{user.id}/{source_raw.content_hash}/fork-{uuid_module.uuid4().hex[:8]}-{source_raw.original_filename}"
    upload_bytes(source_raw.storage_bucket, fork_key, raw_bytes)
    stored_fork_bytes = download_bytes(source_raw.storage_bucket, fork_key)
    fork_checksum = checksum_bytes(stored_fork_bytes)
    if fork_checksum != checksum_bytes(raw_bytes):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Forked raw object could not be checksum-verified after storage.",
        )

    forked_raw = RawFile(
        owner_id=user.id,
        modality=source_raw.modality,
        storage_bucket=source_raw.storage_bucket,
        storage_key=fork_key,
        original_filename=source_raw.original_filename,
        content_hash=fork_checksum,
        storage_version=f"sha256:{fork_checksum}",
        checksum_verified_at=datetime.now(UTC),
        file_size_bytes=source_raw.file_size_bytes,
        vendor_format=source_raw.vendor_format,
        upload_status=source_raw.upload_status,
    )
    db.add(forked_raw)
    db.flush()

    source_job = ingestion_job_for_raw(source.raw_file_id, db)
    fork_job = None
    if source_job is not None:
        fork_job = IngestionJob(
            raw_file_id=forked_raw.id,
            status=source_job.status,
            parser_used=source_job.parser_used,
            parser_version=source_job.parser_version,
            parser_confidence=source_job.parser_confidence,
            canonicalization_version=source_job.canonicalization_version,
            header_hash=source_job.header_hash,
            extracted_metadata_raw=source_job.extracted_metadata_raw,
            extracted_metadata_confirmed=source_job.extracted_metadata_confirmed,
            sanity_check_flags=source_job.sanity_check_flags,
            confirmed_at=source_job.confirmed_at,
            finished_at=datetime.now(UTC),
        )
        db.add(fork_job)

    fork = Spectrum(
        raw_file_id=forked_raw.id,
        owner_id=user.id,
        modality=source.modality,
        title=f"{source.title} (fork)" if source.title else "Fork",
        description=source.description,
        confirmed_metadata=source.confirmed_metadata,
        quality_flags=source.quality_flags,
        canonicalization_version=source.canonicalization_version,
        parent_spectrum_id=source.id,
        material_type=source.material_type,
        state=SpectrumState.draft,
    )
    db.add(fork)
    db.flush()
    if fork_job is not None:
        fork_job.draft_spectrum_id = fork.id
        db.add(fork_job)

    # Replay the source's current ledger onto the fork so it opens looking
    # identical. Imported here (not at module top) to keep the router
    # modules' import graph acyclic-by-construction.
    if source.current_ledger_id is not None:
        from app.routers.ledgers import LedgerStepIn, build_and_persist_ledger

        source_ledger = db.get(ProcessingLedger, source.current_ledger_id)
        if source_ledger is not None:
            steps_in = [
                LedgerStepIn(type=step["type"], params=step["params"], order=step["order"])
                for step in source_ledger.steps
            ]
            ledger_row, _ledger, _reused = build_and_persist_ledger(
                forked_raw, steps_in, db, user
            )
            fork.current_ledger_id = ledger_row.id

    _recompute_derived_fields(fork, db)
    db.add(fork)
    db.commit()
    db.refresh(fork)

    return _serialize(fork, db, user)


@router.post("/spectra/{spectrum_id}/release-embargo", response_model=SpectrumResponse)
def release_embargo(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    spectrum = _get_owned_spectrum_or_404(spectrum_id, user, db)
    spectrum = release_embargo_early(spectrum, db)
    return _serialize(spectrum, db, user)
