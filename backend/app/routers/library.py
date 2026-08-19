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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.enums import Modality
from app.models.spectrum import Spectrum
from app.models.user import User
from app.routers.search import SpectrumSearchResult, serialize_search_result

router = APIRouter(tags=["library"])


@router.get("/library/mine", response_model=list[SpectrumSearchResult])
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
) -> list[SpectrumSearchResult]:
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
    return [serialize_search_result(s) for s in query.all()]
