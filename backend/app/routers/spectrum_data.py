"""Chart-ready spectrum data endpoint (Module 3 visualization).

Mounted with no prefix — `GET /spectra/{spectrum_id}/data`. Returns the
(possibly LTTB-downsampled) (wavenumbers, intensities) pair for a spectrum's
current processed output (or its raw data, if no ledger has been attached
yet or `?raw=true` is passed), gated by the same owner-or-public visibility
rule as every other spectrum-derived read.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_optional
from app.db.session import get_db
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.cache import get_or_compute
from app.processing.state_machine import require_owner_or_public
from app.raman_contract import RamanDataError
from app.schemas.ledger import Ledger, LedgerStep
from app.spectra_io import load_raw_spectrum, lttb_downsample

router = APIRouter(tags=["spectrum-data"])

DEFAULT_MAX_POINTS = 2000


class SpectrumDataResponse(BaseModel):
    wavenumbers: list[float]
    intensities: list[float]
    downsampled: bool
    total_points: int


@router.get("/spectra/{spectrum_id}/data", response_model=SpectrumDataResponse)
def get_spectrum_data(
    spectrum_id: UUID,
    max_points: int = Query(DEFAULT_MAX_POINTS, gt=0),
    raw: bool = Query(
        False,
        description="Return the unprocessed spectrum, ignoring any attached ledger. "
        "Used to overlay before/after while building a processing pipeline.",
    ),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> SpectrumDataResponse:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)

    try:
        if spectrum.current_ledger_id is not None and not raw:
            ledger_row = db.get(ProcessingLedger, spectrum.current_ledger_id)
            if ledger_row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
            ledger = Ledger(
                schema_version=ledger_row.schema_version,
                raw_file_id=ledger_row.raw_file_id,
                steps=[LedgerStep.model_validate(step) for step in ledger_row.steps],
            )
            wavenumbers, intensities = get_or_compute(spectrum.raw_file_id, ledger, db)
        else:
            raw_file = db.get(RawFile, spectrum.raw_file_id)
            if raw_file is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
            wavenumbers, intensities = load_raw_spectrum(raw_file)
    except RamanDataError as exc:
        # The upload has a readable header but no chartable trace (header-only
        # export, unreadable data layout, canonicalization failure). That's a
        # property of the file, not a server fault — 422, not 500, so the UI
        # can show "preview unavailable" instead of crashing.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This file doesn't contain a readable spectral trace to plot.",
        ) from exc

    total_points = int(wavenumbers.shape[0])
    downsampled = False
    if total_points > max_points:
        wavenumbers, intensities = lttb_downsample(wavenumbers, intensities, max_points)
        downsampled = True

    return SpectrumDataResponse(
        wavenumbers=[float(v) for v in wavenumbers],
        intensities=[float(v) for v in intensities],
        downsampled=downsampled,
        total_points=total_points,
    )
