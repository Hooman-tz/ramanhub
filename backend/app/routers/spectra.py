"""Spectrum CRUD-lite + publish/embargo lifecycle + fork endpoints.

Mounted with no prefix (paths below are the full route) — `/spectra`,
`/spectra/{spectrum_id}`, `/spectra/{spectrum_id}/publish`,
`/spectra/{spectrum_id}/release-embargo`, `/spectra/{spectrum_id}/fork`.
"""
from __future__ import annotations

import logging
import uuid as uuid_module
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.accession import next_spectrum_accession
from app.models.enums import SpectrumState
from app.models.processing_ledger import ProcessingLedger
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
from app.schemas.ledger import Ledger, LedgerStep
from app.spectra_io import compute_snr, load_raw_spectrum
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
    accession: str | None
    raw_file_id: UUID
    owner_id: UUID
    modality: str
    title: str | None
    description: str | None
    confirmed_metadata: dict | None
    material_type: str | None
    current_ledger_id: UUID | None
    license_id: str | None
    state: str
    embargo_release_at: datetime | None
    published_at: datetime | None
    doi: str | None
    created_at: datetime
    updated_at: datetime
    ledger_steps: list | None = None

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


def _serialize(spectrum: Spectrum, db: Session) -> SpectrumResponse:
    ledger_steps = None
    if spectrum.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, spectrum.current_ledger_id)
        if ledger_row is not None:
            ledger_steps = ledger_row.steps
    payload = SpectrumResponse.model_validate(spectrum)
    payload.state = effective_state(spectrum)
    payload.ledger_steps = ledger_steps
    return payload


def _get_owned_spectrum_or_404(spectrum_id: UUID, user: User, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None or spectrum.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return spectrum


@router.post("/spectra", response_model=SpectrumResponse, status_code=status.HTTP_201_CREATED)
def create_spectrum(
    body: SpectrumCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    raw_file = db.get(RawFile, body.raw_file_id)
    if raw_file is None or raw_file.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Raw file not found")

    if body.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, body.current_ledger_id)
        if ledger_row is None or ledger_row.raw_file_id != raw_file.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="current_ledger_id does not reference a ledger for this raw file",
            )

    spectrum = Spectrum(
        # Assigned at creation, not at publish: a draft that gets forked,
        # cited in a lab notebook, or referenced in a Finding needs a stable
        # public handle before it's public. Gaps in the series from deleted
        # drafts are expected and harmless (see app.models.accession).
        accession=next_spectrum_accession(db),
        raw_file_id=raw_file.id,
        owner_id=user.id,
        modality=raw_file.modality,
        title=body.title,
        description=body.description,
        confirmed_metadata=body.confirmed_metadata,
        material_type=body.material_type,
        current_ledger_id=body.current_ledger_id,
        state=SpectrumState.draft,
    )
    _recompute_derived_fields(spectrum, db)
    db.add(spectrum)
    db.commit()
    db.refresh(spectrum)
    return _serialize(spectrum, db)


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
    return _serialize(spectrum, db)


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
        spectrum.confirmed_metadata = body.confirmed_metadata
    if body.material_type is not None:
        spectrum.material_type = body.material_type

    _recompute_derived_fields(spectrum, db)

    db.add(spectrum)
    db.commit()
    db.refresh(spectrum)
    return _serialize(spectrum, db)


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
    if body.embargo_release_at is not None:
        spectrum = embargo(spectrum, body.license_id, body.embargo_release_at, db, doi=body.doi)
    else:
        spectrum = publish(spectrum, body.license_id, db, doi=body.doi)
    return _serialize(spectrum, db)


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
    fork_key = f"{user.id}/{source_raw.content_hash}/fork-{uuid_module.uuid4().hex[:8]}-{source_raw.original_filename}"
    upload_bytes(source_raw.storage_bucket, fork_key, raw_bytes)

    forked_raw = RawFile(
        owner_id=user.id,
        modality=source_raw.modality,
        storage_bucket=source_raw.storage_bucket,
        storage_key=fork_key,
        original_filename=source_raw.original_filename,
        content_hash=source_raw.content_hash,
        file_size_bytes=source_raw.file_size_bytes,
        vendor_format=source_raw.vendor_format,
        upload_status=source_raw.upload_status,
    )
    db.add(forked_raw)
    db.flush()

    fork = Spectrum(
        # A fork is a distinct record with its own lifecycle, so it gets its
        # own accession rather than inheriting the source's — two records
        # sharing a citable identifier is exactly what accessions must never
        # allow.
        accession=next_spectrum_accession(db),
        raw_file_id=forked_raw.id,
        owner_id=user.id,
        modality=source.modality,
        title=f"{source.title} (fork)" if source.title else "Fork",
        description=source.description,
        confirmed_metadata=source.confirmed_metadata,
        material_type=source.material_type,
        state=SpectrumState.draft,
    )
    db.add(fork)
    db.flush()

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

    return _serialize(fork, db)


@router.post("/spectra/{spectrum_id}/release-embargo", response_model=SpectrumResponse)
def release_embargo(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    spectrum = _get_owned_spectrum_or_404(spectrum_id, user, db)
    spectrum = release_embargo_early(spectrum, db)
    return _serialize(spectrum, db)
