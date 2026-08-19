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
from app.processing.state_machine import (
    effective_state,
    embargo,
    publish,
    release_embargo_early,
    require_owner_or_public,
)

router = APIRouter(tags=["spectra"])


class SpectrumCreate(BaseModel):
    raw_file_id: UUID
    current_ledger_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    confirmed_metadata: dict | None = None


class SpectrumUpdate(BaseModel):
    current_ledger_id: UUID | None = None
    title: str | None = None
    description: str | None = None
    confirmed_metadata: dict | None = None


class PublishRequest(BaseModel):
    license_id: str
    embargo_release_at: datetime | None = None


class SpectrumResponse(BaseModel):
    id: UUID
    raw_file_id: UUID
    owner_id: UUID
    modality: str
    title: str | None
    description: str | None
    confirmed_metadata: dict | None
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
        current_ledger_id=body.current_ledger_id,
        state=SpectrumState.draft,
    )
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
    if body.embargo_release_at is not None:
        spectrum = embargo(spectrum, body.license_id, body.embargo_release_at, db)
    else:
        spectrum = publish(spectrum, body.license_id, db)
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
