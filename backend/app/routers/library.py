"""Module 4a: private per-user reference library — same objective-metadata
filters as `/search/spectra` (see `app.routers.search`), but scoped to the
requester's own spectra across every state (draft/published/embargoed), not
just the shared public commons.

"Promotable into the public database" (per the architecture doc) is just the
existing publish flow (`POST /spectra/{id}/publish`) — no separate promote
endpoint here; the library UI links out to that existing action.

Mounted with no prefix — `GET /library/mine`.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.enums import Modality
from app.models.spectrum import Spectrum
from app.models.user import User
from app.routers.search import SpectrumSearchResult, serialize_search_result
from app.spectrum_lifecycle import publication_readiness

router = APIRouter(tags=["library"])


class LibrarySpectrumResult(SpectrumSearchResult):
    """Private-library list row with compact, non-sensitive trust signals."""

    raw_file_id: str
    metadata_state: str
    qc_state: str
    publish_ready: bool
    # Drafts have no `published_at`, so it is the only timestamp a client can
    # order the owner's own library by — without it a freshly uploaded
    # spectrum is indistinguishable from one with no date at all. Added here
    # rather than on `SpectrumSearchResult` so the public `/search/spectra`
    # shape is unchanged.
    created_at: datetime


def _serialize_library_result(spectrum: Spectrum, db: Session) -> LibrarySpectrumResult:
    base = serialize_search_result(spectrum)
    readiness = publication_readiness(spectrum, db)
    return LibrarySpectrumResult(
        **base.model_dump(),
        raw_file_id=str(spectrum.raw_file_id),
        metadata_state=readiness["metadata_state"],
        qc_state=readiness["qc_state"],
        publish_ready=readiness["ready"],
        created_at=spectrum.created_at,
    )


@router.get("/library/mine", response_model=list[LibrarySpectrumResult])
def get_my_library(
    material_type: str | None = None,
    excitation_wavelength_nm: float | None = None,
    excitation_wavelength_tolerance_nm: float = 5.0,
    min_snr: float | None = None,
    modality: str | None = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[LibrarySpectrumResult]:
    """The requester's private reference library: every spectrum they own,
    in any state (draft/published/embargoed all visible to the owner here —
    unlike `/search/spectra`, which is published-only). No `trust_tier`
    filter (doesn't make much sense scoped to a single owner's own items).
    Ordered by `created_at desc` (most recently added first)."""
    query = db.query(Spectrum).filter(Spectrum.owner_id == user.id)

    if material_type:
        query = query.filter(Spectrum.material_type.ilike(f"%{material_type}%"))
    if modality:
        try:
            modality_value = Modality(modality)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Unknown modality: {modality!r}"
            ) from exc
        query = query.filter(Spectrum.modality == modality_value)
    if min_snr is not None:
        query = query.filter(Spectrum.snr.is_not(None), Spectrum.snr >= min_snr)
    if excitation_wavelength_nm is not None:
        tolerance = abs(excitation_wavelength_tolerance_nm)
        query = query.filter(
            Spectrum.excitation_wavelength_nm.is_not(None),
            Spectrum.excitation_wavelength_nm >= excitation_wavelength_nm - tolerance,
            Spectrum.excitation_wavelength_nm <= excitation_wavelength_nm + tolerance,
        )

    query = query.order_by(Spectrum.created_at.desc()).offset(offset).limit(limit)
    return [_serialize_library_result(spectrum, db) for spectrum in query.all()]
