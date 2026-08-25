"""Chart-ready spectrum data endpoints (Module 3 visualization).

Mounted with no prefix:

* `GET  /spectra/{spectrum_id}/data`    — the committed view
* `POST /spectra/{spectrum_id}/preview` — an uncommitted, hypothetical view

`/data` returns the (possibly LTTB-downsampled) (wavenumbers, intensities)
pair for a spectrum's current processed output (or its raw data, if no
ledger has been attached yet or `?raw=true` is passed).

`/preview` answers "what WOULD this pipeline do", replaying a client-supplied
step list against the raw arrays and persisting nothing — see
`app.processing.preview` for why that needs its own compute path rather than
the caching one. It is a POST because the pipeline goes in the body: a
multi-step pipeline with nested params does not survive a query string, and
putting it there would also log every parameter a user tried into access
logs. Both routes are gated by the same owner-or-public visibility rule as
every other spectrum-derived read.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_optional
from app.db.session import get_db
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.cache import get_or_compute
from app.processing.preview import (
    MAX_PREVIEW_STEPS,
    PreviewError,
    build_steps,
    compute_preview,
)
from app.processing.state_machine import require_owner_or_public
from app.ratelimit import rate_limit_previews
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


class PreviewStepIn(BaseModel):
    """Client-supplied step. No `version` — the server resolves the step type
    to whichever algorithm version this codebase implements, exactly as the
    commit path (`routers.ledgers.LedgerStepIn`) does, so a previewed pipeline
    and the ledger built from it can never disagree about versions."""

    type: str
    params: dict = Field(default_factory=dict)
    order: int


class PreviewRequest(BaseModel):
    steps: list[PreviewStepIn] = Field(default_factory=list, max_length=MAX_PREVIEW_STEPS)
    max_points: int = Field(DEFAULT_MAX_POINTS, gt=0)


@router.post("/spectra/{spectrum_id}/preview", response_model=SpectrumDataResponse)
def preview_pipeline(
    spectrum_id: UUID,
    body: PreviewRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
    _: None = Depends(rate_limit_previews),
) -> SpectrumDataResponse:
    """Replay a hypothetical pipeline and return the resulting curve.

    Nothing is written: no ledger, no processed-cache row, no storage object.
    An empty `steps` list is legal and returns the raw spectrum, which is
    what makes "remove the last step" previewable all the way back to zero.
    """
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)

    raw_file = db.get(RawFile, spectrum.raw_file_id)
    if raw_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    try:
        steps = build_steps([(s.type, s.params, s.order) for s in body.steps])
        wavenumbers, intensities = compute_preview(raw_file, steps, db)
    except PreviewError as exc:
        # Always client input, never a server fault — see PreviewError.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    total_points = int(wavenumbers.shape[0])
    downsampled = False
    if total_points > body.max_points:
        wavenumbers, intensities = lttb_downsample(wavenumbers, intensities, body.max_points)
        downsampled = True

    return SpectrumDataResponse(
        wavenumbers=[float(v) for v in wavenumbers],
        intensities=[float(v) for v in intensities],
        downsampled=downsampled,
        total_points=total_points,
    )
