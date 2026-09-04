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
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_optional
from app.db.session import get_db
from app.discovery.raman_similarity import (
    FEATURE_VERSION,
    compatible,
    cosine_feature_similarity,
    warm_features,
)
from app.models.enums import Modality, SpectrumState
from app.models.processing_ledger import ProcessingLedger
from app.models.publication import PublicationSnapshot
from app.models.reference import ReferenceEntry
from app.models.similarity import SimilarityFeature
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.cache import get_or_compute
from app.processing.state_machine import effective_state, require_owner_or_public
from app.schemas.ledger import Ledger, LedgerStep
from app.spectra_io import load_spectrum_trace

router = APIRouter(prefix="/search", tags=["search"])


def _exclude_reference_library(query):
    """Keep the bundled reference corpus out of the community commons.

    The reference library is thousands of published, visible spectra that all
    share a seeding timestamp. Left in, they would bury real user uploads in
    `/search/spectra` (which orders by `published_at desc`) and dominate the
    brute-force candidate set in `/search/similar`. They are not hidden — they
    have their own surface at `/v1/library/*`, which is index-served and knows
    how to rank them. This endpoint is discovery over user-contributed
    science; identification against known compounds is a different question.
    """
    return query.outerjoin(
        ReferenceEntry, ReferenceEntry.spectrum_id == Spectrum.id
    ).filter(ReferenceEntry.id.is_(None))


class SpectrumSearchResult(BaseModel):
    """Lightweight search-result shape — deliberately NOT the full
    `SpectrumResponse` (no `ledger_steps`/`confirmed_metadata`); search
    results should stay cheap to list in bulk. Reused as-is by
    `app.routers.library` for `/library/mine` (the `state` field is what
    lets the library UI show draft/published/embargoed badges; for
    `/search/spectra` it will always be `"published"` given that endpoint's
    filter)."""

    id: UUID
    title: str | None
    material_type: str | None
    excitation_wavelength_nm: float | None
    snr: float | None
    modality: str
    doi: str | None
    published_at: datetime | None
    state: str

    model_config = {"from_attributes": True}


class SimilarSpectrumResult(BaseModel):
    spectrum: SpectrumSearchResult
    similarity: float
    overlap_fraction: float


def serialize_search_result(spectrum: Spectrum) -> SpectrumSearchResult:
    result = SpectrumSearchResult.model_validate(spectrum)
    result.state = effective_state(spectrum)
    return result


def load_spectrum_arrays(spectrum: Spectrum, db: Session) -> tuple[np.ndarray, np.ndarray]:
    """Resolve `(wavenumbers, intensities)` for a spectrum using the same
    "processed-if-ledgered, else raw" pattern used by
    `app.routers.spectra._recompute_derived_fields` and Module 3's
    visualization endpoints. Shared here so both `/search/spectra`-adjacent
    similarity search and any future caller can reuse it without
    reimplementing the ledger-reconstruction dance."""
    if spectrum.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, spectrum.current_ledger_id)
        if ledger_row is not None:
            ledger = Ledger(
                schema_version=ledger_row.schema_version,
                raw_file_id=ledger_row.raw_file_id,
                steps=[LedgerStep.model_validate(step) for step in ledger_row.steps],
            )
            return get_or_compute(spectrum.raw_file_id, ledger, db, spectrum=spectrum)
    return load_spectrum_trace(spectrum, db)


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
    query = _exclude_reference_library(
        db.query(Spectrum).filter(
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == "visible",
        )
    )

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
        query = query.join(
            PublicationSnapshot, PublicationSnapshot.spectrum_id == Spectrum.id
        ).filter(PublicationSnapshot.verification_status == "verified")
    elif trust_tier == "community":
        query = query.outerjoin(
            PublicationSnapshot, PublicationSnapshot.spectrum_id == Spectrum.id
        ).filter(
            or_(
                PublicationSnapshot.id.is_(None),
                PublicationSnapshot.verification_status != "verified",
            )
        )

    query = query.order_by(Spectrum.published_at.desc()).offset(offset).limit(limit)
    return [serialize_search_result(s) for s in query.all()]


@router.get("/similar/{spectrum_id}", response_model=list[SimilarSpectrumResult])
def search_similar(
    spectrum_id: UUID,
    top_k: int = 10,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[SimilarSpectrumResult]:
    """Cosine nearest-neighbor search over persisted Raman feature vectors.

    The target itself must be published or owned by the requester (reuses
    `require_owner_or_public`, so drafts stay private); candidates are
    always restricted to visible published spectra regardless of who's asking.
    A cold request warms missing compact features once; subsequent requests
    query those features rather than replaying every raw file. The exact
    scorer remains intentional until index-coverage/latency measurements show
    that additional infrastructure is warranted.
    """
    target = db.get(Spectrum, spectrum_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(target, user)

    candidates = (
        _exclude_reference_library(
            db.query(Spectrum).filter(
                Spectrum.state == SpectrumState.published,
                Spectrum.moderation_status == "visible",
                Spectrum.id != target.id,
            )
        )
        .all()
    )
    candidate_ids = [candidate.id for candidate in candidates]
    try:
        features = warm_features([target.id, *candidate_ids], db)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Similarity feature could not be built: {exc}") from exc
    by_spectrum_id = {feature.spectrum_id: feature for feature in features}
    target_feature = by_spectrum_id.get(target.id)
    if target_feature is None or not target_feature.qc_eligible:
        return []

    scored: list[tuple[float, float, Spectrum]] = []
    for candidate in candidates:
        feature = by_spectrum_id.get(candidate.id)
        if feature is None:
            continue
        is_compatible, overlap = compatible(target_feature, feature)
        if is_compatible:
            scored.append((cosine_feature_similarity(target_feature, feature), overlap, candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        SimilarSpectrumResult(
            spectrum=serialize_search_result(candidate),
            similarity=similarity,
            overlap_fraction=overlap,
        )
        for similarity, overlap, candidate in scored[:top_k]
    ]


@router.get("/index-status")
def similarity_index_status(db: Session = Depends(get_db)) -> dict[str, int | str]:
    """Measured exact-index coverage; avoids premature index infrastructure."""
    eligible = (
        db.query(Spectrum)
        .filter(
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == "visible",
            Spectrum.modality == Modality.raman,
        )
        .count()
    )
    indexed = (
        db.query(SimilarityFeature)
        .filter(
            SimilarityFeature.feature_version == FEATURE_VERSION,
            SimilarityFeature.qc_eligible.is_(True),
        )
        .count()
    )
    return {
        "feature_version": FEATURE_VERSION,
        "eligible_spectra": eligible,
        "indexed_spectra": indexed,
        "unindexed_spectra": max(eligible - indexed, 0),
    }
