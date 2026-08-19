"""Spectrum CRUD-lite + publish/embargo lifecycle endpoints.

Mounted with no prefix (paths below are the full route) — `/spectra`,
`/spectra/{spectrum_id}`, `/spectra/{spectrum_id}/publish`,
`/spectra/{spectrum_id}/release-embargo`.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
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

router = APIRouter(tags=["spectra"])


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
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    spectrum = _get_owned_spectrum_or_404(spectrum_id, user, db)
    _recompute_derived_fields(spectrum, db)
    if body.embargo_release_at is not None:
        spectrum = embargo(spectrum, body.license_id, body.embargo_release_at, db, doi=body.doi)
    else:
        spectrum = publish(spectrum, body.license_id, db, doi=body.doi)
    return _serialize(spectrum, db)


@router.post("/spectra/{spectrum_id}/release-embargo", response_model=SpectrumResponse)
def release_embargo(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SpectrumResponse:
    spectrum = _get_owned_spectrum_or_404(spectrum_id, user, db)
    spectrum = release_embargo_early(spectrum, db)
    return _serialize(spectrum, db)
