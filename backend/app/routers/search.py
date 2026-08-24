"""Module 4a: core objective-metadata search + spectral similarity search
over the shared public commons.

Mounted with no prefix (this router itself declares `prefix="/search"`) —
`GET /search/spectra`, `GET /search/similar/{spectrum_id}`.

Deliberately NOT touching social signals (votes/comments/trending — owned by
a different Module 4b router) anywhere in this file: no join against
`app.models.social`, no ordering by anything but `published_at`. Per the
architecture doc, core search/ranking must stay quarantined from social
voting.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_optional
from app.db.session import get_db
from app.models.enums import Modality, SpectrumState
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import effective_state, require_owner_or_public
from app.spectrum_access import load_spectrum_arrays

router = APIRouter(prefix="/search", tags=["search"])


class SpectrumSearchResult(BaseModel):
    """Lightweight search-result shape — deliberately NOT the full
    `SpectrumResponse` (no `ledger_steps`/`confirmed_metadata`); search
    results should stay cheap to list in bulk. Reused as-is by
    `app.routers.library` for `/library/mine` (the `state` field is what
    lets the library UI show draft/published/embargoed badges; for
    `/search/spectra` it will always be `"published"` given that endpoint's
    filter)."""

    id: UUID
    accession: str | None
    title: str | None
    material_type: str | None
    excitation_wavelength_nm: float | None
    snr: float | None
    modality: str
    doi: str | None
    owner_id: UUID
    published_at: datetime | None
    state: str

    model_config = {"from_attributes": True}


class SimilarSpectrumResult(BaseModel):
    spectrum: SpectrumSearchResult
    similarity: float


def serialize_search_result(spectrum: Spectrum) -> SpectrumSearchResult:
    result = SpectrumSearchResult.model_validate(spectrum)
    result.state = effective_state(spectrum)
    return result


def cosine_similarity(
    target_wavenumbers: np.ndarray,
    target_intensities: np.ndarray,
    candidate_wavenumbers: np.ndarray,
    candidate_intensities: np.ndarray,
) -> float | None:
    """Cosine similarity between two spectra.

    v1 approach: resample the candidate onto the TARGET's own wavenumber
    grid via linear interpolation (`np.interp`) before comparing, rather
    than only comparing same-length arrays. Real spectra routinely differ in
    array length/wavenumber range (different instruments, resolutions,
    ledgers), and interpolation handles that gracefully as long as the two
    ranges reasonably overlap — `np.interp` clamps out-of-range target
    points to the candidate's nearest edge value, which is an acceptable v1
    approximation, not a rigorous resampling (no extrapolation, no
    handling of wildly non-overlapping ranges beyond "the edge value gets
    reused"). Returns `None` if either array is empty or the norm product is
    zero (degenerate/flat array — cosine similarity undefined).
    """
    if target_wavenumbers.size == 0 or candidate_wavenumbers.size == 0:
        return None
    # np.interp requires x (candidate_wavenumbers) to be increasing.
    order = np.argsort(candidate_wavenumbers)
    cand_wn_sorted = candidate_wavenumbers[order]
    cand_intensity_sorted = candidate_intensities[order]
    resampled = np.interp(target_wavenumbers, cand_wn_sorted, cand_intensity_sorted)

    denom = float(np.linalg.norm(target_intensities) * np.linalg.norm(resampled))
    if denom == 0.0:
        return None
    return float(np.dot(target_intensities, resampled) / denom)


@router.get("/spectra", response_model=list[SpectrumSearchResult])
def search_spectra(
    material_type: str | None = None,
    excitation_wavelength_nm: float | None = None,
    excitation_wavelength_tolerance_nm: float = 5.0,
    min_snr: float | None = None,
    modality: str | None = None,
    trust_tier: Literal["doi_verified", "community"] | None = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[SpectrumSearchResult]:
    """Core objective-metadata search over the shared public commons.
    Public, no auth required. Published spectra only — drafts/embargoed
    never appear here, even to their owner (use `/library/mine` for that).

    Simplification (documented per spec): filters on `state ==
    SpectrumState.published` only. An embargoed spectrum whose
    `embargo_release_at` has already passed but hasn't otherwise triggered a
    write (e.g. `POST .../release-embargo`) will NOT show up here yet, even
    though `effective_state()` would consider it published for read-access
    purposes elsewhere — there's no background sweeper that flips `state` in
    the DB (see `state_machine`'s module docstring). Acceptable v1 tradeoff,
    not a security issue (`require_owner_or_public` still gates individual
    reads correctly).

    Ordering: `published_at desc` ONLY, never any popularity/vote signal —
    Module 4b's vote/comment counts must never appear in this endpoint's
    filtering or ordering.
    """
    query = db.query(Spectrum).filter(Spectrum.state == SpectrumState.published)

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
    if trust_tier == "doi_verified":
        query = query.filter(Spectrum.doi.is_not(None))
    elif trust_tier == "community":
        query = query.filter(Spectrum.doi.is_(None))

    query = query.order_by(Spectrum.published_at.desc()).offset(offset).limit(limit)
    return [serialize_search_result(s) for s in query.all()]


@router.get("/similar/{spectrum_id}", response_model=list[SimilarSpectrumResult])
def search_similar(
    spectrum_id: UUID,
    top_k: int = 10,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[SimilarSpectrumResult]:
    """Cosine-similarity nearest-neighbor search: compares `spectrum_id`'s
    processed (or raw) intensity array against every OTHER published
    spectrum's array, returns the `top_k` most similar, sorted descending.

    The target itself must be published or owned by the requester (reuses
    `require_owner_or_public`, so drafts stay private); candidates are
    always restricted to published spectra regardless of who's asking.

    Deliberately O(n) full-corpus, in-Python: no vector index/pgvector/
    caching layer. Fine for "hundreds to low thousands of users" per the
    architecture doc's Scaling Posture; not fine at a much larger corpus
    size, but that's a "when we have evidence we need it" problem, not a v1
    one.
    """
    target = db.get(Spectrum, spectrum_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(target, user)

    target_wavenumbers, target_intensities = load_spectrum_arrays(target, db)
    if target_intensities.size == 0:
        return []

    candidates = (
        db.query(Spectrum)
        .filter(Spectrum.state == SpectrumState.published, Spectrum.id != target.id)
        .all()
    )

    scored: list[tuple[float, Spectrum]] = []
    for candidate in candidates:
        try:
            cand_wavenumbers, cand_intensities = load_spectrum_arrays(candidate, db)
        except Exception:  # noqa: BLE001, S112 - one bad candidate must not fail the whole search
            continue
        if cand_intensities.size == 0:
            continue
        similarity = cosine_similarity(
            target_wavenumbers, target_intensities, cand_wavenumbers, cand_intensities
        )
        if similarity is None:
            continue
        scored.append((similarity, candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        SimilarSpectrumResult(spectrum=serialize_search_result(candidate), similarity=similarity)
        for similarity, candidate in scored[:top_k]
    ]
