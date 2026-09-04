"""The public reference library: identify a spectrum against known compounds.

Not to be confused with `app.routers.library`, which serves the unversioned
`GET /library/mine` — *your own* spectra in every state. This router serves
`/v1/library/*`: the shared corpus of identified compounds that anyone can
match against. Different data, different audience, different trust model.

Numerics live in `app.discovery.library_match`; this file is HTTP, auth and
serialization only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import (
    get_current_full_user,
    get_current_moderator,
    get_current_user_optional,
)
from app.db.session import get_db
from app.discovery.library_match import (
    MATCH_CONTRACT_VERSION,
    UNMIX_MAX_COMPONENTS,
    match_against_library,
    unmix,
)
from app.discovery.peak_index import get_or_build_peak_index
from app.discovery.raman_similarity import get_or_build_feature
from app.models.enums import (
    Modality,
    ReferenceCurationStatus,
    ReferenceTrustTier,
    SpectrumState,
)
from app.models.reference import ReferenceEntry
from app.models.spectrum import Spectrum
from app.models.spectrum_peaks import SpectrumPeaks
from app.models.user import User
from app.processing.state_machine import require_owner_or_public
from app.ratelimit import (
    rate_limit_library_match,
    rate_limit_library_unmix,
    rate_limit_search_browse,
)
from app.textsearch import apply_threshold, text_predicate, text_rank

router = APIRouter(prefix="/v1/library", tags=["reference-library"])

TrustTierLiteral = Literal["curated", "community"]


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


class PeakOut(BaseModel):
    cm1: float
    height: float
    rel_height: float
    prominence: float
    fwhm: float | None = None
    snr: float | None = None


class ReferenceEntryOut(BaseModel):
    id: UUID
    spectrum_id: UUID
    compound_name: str
    chemical_formula: str | None = None
    cas_number: str | None = None
    mineral_name: str | None = None
    source: str
    source_id: str | None = None
    source_dataset: str | None = None
    provenance_url: str | None = None
    trust_tier: str
    curation_status: str
    flagged_for_review: bool
    license_id: str | None = None
    title: str | None = None
    excitation_wavelength_nm: float | None = None
    primary_peak_cm1: float | None = None


def _serialize(
    entry: ReferenceEntry,
    spectrum: Spectrum | None = None,
    peaks: SpectrumPeaks | None = None,
) -> ReferenceEntryOut:
    return ReferenceEntryOut(
        id=entry.id,
        spectrum_id=entry.spectrum_id,
        compound_name=entry.compound_name,
        chemical_formula=entry.chemical_formula,
        cas_number=entry.cas_number,
        mineral_name=entry.mineral_name,
        source=entry.source,
        source_id=entry.source_id,
        source_dataset=entry.source_dataset,
        provenance_url=entry.provenance_url,
        trust_tier=entry.trust_tier.value
        if hasattr(entry.trust_tier, "value")
        else str(entry.trust_tier),
        curation_status=entry.curation_status.value
        if hasattr(entry.curation_status, "value")
        else str(entry.curation_status),
        flagged_for_review=entry.flagged_for_review,
        license_id=getattr(spectrum, "license_id", None),
        title=getattr(spectrum, "title", None),
        excitation_wavelength_nm=getattr(spectrum, "excitation_wavelength_nm", None),
        primary_peak_cm1=getattr(peaks, "primary_peak_cm1", None),
    )


# --------------------------------------------------------------------------
# Browse
# --------------------------------------------------------------------------


@router.get(
    "/references",
    response_model=list[ReferenceEntryOut],
    dependencies=[Depends(rate_limit_search_browse)],
)
def search_references(
    q: str | None = None,
    formula: str | None = None,
    cas_number: str | None = None,
    source: str | None = None,
    trust_tier: TrustTierLiteral | None = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[ReferenceEntryOut]:
    """Browse the reference corpus by compound identity.

    Shares `/search/spectra`'s filter idiom, pagination defaults and bare-list
    return shape (so the web app's existing "Load more" pattern works
    unchanged), but is a distinct endpoint because it queries
    `reference_entries JOIN spectra` and returns a *compound identity* rather
    than a spectrum record. Folding this into `/search/spectra` would make
    `SpectrumSearchResult` grow eight nullable columns that are NULL for the
    overwhelming majority of published spectra.
    """
    limit = max(1, min(limit, 100))
    query = (
        db.query(ReferenceEntry, Spectrum)
        .join(Spectrum, Spectrum.id == ReferenceEntry.spectrum_id)
        .filter(ReferenceEntry.curation_status != ReferenceCurationStatus.removed)
    )
    q = q.strip() if q else None
    if q:
        apply_threshold(db)
        query = query.filter(text_predicate(ReferenceEntry.search_text, q))
    if formula:
        query = query.filter(ReferenceEntry.chemical_formula.ilike(f"%{formula}%"))
    if cas_number:
        query = query.filter(ReferenceEntry.cas_number == cas_number)
    if source:
        query = query.filter(ReferenceEntry.source == source)
    if trust_tier:
        query = query.filter(ReferenceEntry.trust_tier == ReferenceTrustTier(trust_tier))

    # Two different questions, so two different orderings.
    #
    # Searching: relevance wins. Someone typing "calcite" wants Calcite, not
    # whichever match happens to sort first — which is what they used to get.
    # Curation still breaks ties, and no social signal enters either branch,
    # matching the quarantine `search.py` documents.
    #
    # Browsing: curated first, then real names, then alphabetical. The middle
    # term matters: a minority of entries carry a composition string rather
    # than a name ("(Pb1.924 Ba0.018 ...)"), and left to plain alphabetical
    # sorting those parenthesised strings occupy the whole first page — the
    # worst possible first impression of a library that is 94% properly named.
    # This branch is byte-identical to what it was before search ranking
    # existed; changing it would undo that fix.
    if q:
        ordering = (
            text_rank(ReferenceEntry.compound_name, ReferenceEntry.search_text, q).desc(),
            ReferenceEntry.trust_tier.asc(),
            ReferenceEntry.compound_name.asc(),
        )
    else:
        ordering = (
            ReferenceEntry.trust_tier.asc(),
            ReferenceEntry.compound_name.op("~")("^[A-Za-z]").desc(),
            ReferenceEntry.compound_name.asc(),
        )
    rows = (
        query.order_by(*ordering)
        .offset(max(0, offset))
        .limit(limit)
        .all()
    )
    return [_serialize(entry, spectrum) for entry, spectrum in rows]


class ReferenceDetailOut(ReferenceEntryOut):
    peaks: list[PeakOut] = []
    wavenumber_min: float | None = None
    wavenumber_max: float | None = None


@router.get("/references/{reference_id}", response_model=ReferenceDetailOut)
def get_reference(
    reference_id: UUID,
    db: Session = Depends(get_db),
) -> ReferenceDetailOut:
    entry = db.get(ReferenceEntry, reference_id)
    if entry is None or entry.curation_status == ReferenceCurationStatus.removed:
        raise HTTPException(status_code=404, detail="Reference not found.")
    spectrum = db.get(Spectrum, entry.spectrum_id)
    peaks = (
        db.query(SpectrumPeaks)
        .filter(SpectrumPeaks.spectrum_id == entry.spectrum_id)
        .one_or_none()
    )
    base = _serialize(entry, spectrum, peaks)
    return ReferenceDetailOut(
        **base.model_dump(),
        peaks=[PeakOut(**p) for p in (peaks.peaks if peaks else [])],
        wavenumber_min=getattr(peaks, "wavenumber_min", None),
        wavenumber_max=getattr(peaks, "wavenumber_max", None),
    )


# --------------------------------------------------------------------------
# Match
# --------------------------------------------------------------------------


class LibraryMatchRequest(BaseModel):
    spectrum_id: UUID
    top_k: int = Field(default=10, ge=1, le=50)
    trust_tiers: list[TrustTierLiteral] | None = None
    #: Advisory only. The server recomputes peaks and never trusts these; they
    #: are used solely to widen the candidate net, never to narrow it.
    client_peaks_cm1: list[float] | None = Field(default=None, max_length=40)


class LibraryMatchOut(BaseModel):
    reference: ReferenceEntryOut
    similarity: float
    overlap_fraction: float
    matched_peak_count: int
    unmatched_query_peaks_cm1: list[float]


class LibraryMatchResponse(BaseModel):
    contract_version: str
    peak_index_version: str
    feature_version: str
    query_spectrum_id: UUID
    query_peaks: list[PeakOut]
    primary_peak_cm1: float | None
    peak_to_background: float | None
    prefilter_stage: str
    candidates_screened: int
    candidates_scored: int
    matches: list[LibraryMatchOut]
    mixture_suspected: bool
    mixture_reason: str | None
    suggested_component_reference_ids: list[UUID]


def _readable_target(spectrum_id: UUID, db: Session, user: User | None) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=404, detail="Spectrum not found.")
    # Raises 404 (never 403) for a private spectrum, matching the convention
    # every other read path in this codebase uses.
    require_owner_or_public(spectrum, user)
    return spectrum


@router.post("/match", response_model=LibraryMatchResponse)
def match_spectrum(
    body: LibraryMatchRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
    _: None = Depends(rate_limit_library_match),
) -> LibraryMatchResponse:
    """Stage 1: identify a spectrum against the reference corpus."""
    target = _readable_target(body.spectrum_id, db, user)
    tiers = (
        [ReferenceTrustTier(t) for t in body.trust_tiers] if body.trust_tiers else None
    )
    try:
        report = match_against_library(
            target,
            db,
            top_k=body.top_k,
            trust_tiers=tiers,
            client_peaks_cm1=body.client_peaks_cm1,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()

    return LibraryMatchResponse(
        contract_version=report.contract_version,
        peak_index_version=report.peak_index_version,
        feature_version=report.feature_version,
        query_spectrum_id=report.query_spectrum_id,
        query_peaks=[PeakOut(**p) for p in report.query_peaks],
        primary_peak_cm1=report.primary_peak_cm1,
        peak_to_background=report.peak_to_background,
        prefilter_stage=report.prefilter_stage,
        candidates_screened=report.candidates_screened,
        candidates_scored=report.candidates_scored,
        matches=[
            LibraryMatchOut(
                reference=_serialize(hit.entry, hit.spectrum),
                similarity=hit.similarity,
                overlap_fraction=hit.overlap_fraction,
                matched_peak_count=hit.matched_peak_count,
                unmatched_query_peaks_cm1=hit.unmatched_query_peaks_cm1,
            )
            for hit in report.hits
        ],
        mixture_suspected=report.mixture_suspected,
        mixture_reason=report.mixture_reason,
        suggested_component_reference_ids=report.suggested_component_reference_ids,
    )


# --------------------------------------------------------------------------
# Unmix
# --------------------------------------------------------------------------


class LibraryUnmixRequest(BaseModel):
    spectrum_id: UUID
    reference_ids: list[UUID] = Field(min_length=1, max_length=UNMIX_MAX_COMPONENTS)
    grid_points: int = Field(default=512, ge=64, le=2048)
    baseline: Literal["als", "none"] = "als"


class UnmixComponentOut(BaseModel):
    reference: ReferenceEntryOut
    #: Fraction of *spectral contribution*, not concentration. Raman cross
    #: sections differ by orders of magnitude between compounds.
    weight: float
    raw_coefficient: float


class LibraryUnmixResponse(BaseModel):
    contract_version: str
    query_spectrum_id: UUID
    baseline_applied: str
    grid_wavenumbers: list[float]
    observed: list[float]
    fitted: list[float]
    residual: list[float]
    components: list[UnmixComponentOut]
    offset: float
    slope: float
    r_squared: float
    residual_norm_fraction: float
    condition_number: float
    collinear_warnings: list[str]


@router.post("/unmix", response_model=LibraryUnmixResponse)
def unmix_spectrum(
    body: LibraryUnmixRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
    _: None = Depends(rate_limit_library_unmix),
) -> LibraryUnmixResponse:
    """Stage 2: fit the spectrum as a non-negative mixture of chosen references."""
    target = _readable_target(body.spectrum_id, db, user)

    entries = (
        db.query(ReferenceEntry)
        .filter(
            ReferenceEntry.id.in_(body.reference_ids),
            ReferenceEntry.curation_status != ReferenceCurationStatus.removed,
        )
        .all()
    )
    by_id = {e.id: e for e in entries}
    missing = [str(r) for r in body.reference_ids if r not in by_id]
    if missing:
        raise HTTPException(
            status_code=404, detail=f"Unknown reference(s): {', '.join(missing)}"
        )

    # Preserve caller order so the returned components line up with the request.
    pairs: list[tuple[ReferenceEntry, Spectrum]] = []
    for ref_id in body.reference_ids:
        entry = by_id[ref_id]
        spectrum = db.get(Spectrum, entry.spectrum_id)
        if spectrum is None:
            raise HTTPException(
                status_code=404,
                detail=f"Reference {entry.compound_name} has no spectrum.",
            )
        pairs.append((entry, spectrum))

    try:
        report = unmix(
            target, pairs, db, grid_points=body.grid_points, baseline=body.baseline
        )
    except ValueError as exc:
        # Insufficient wavenumber overlap, or nothing explains the signal.
        # A modelling failure, not a server fault.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return LibraryUnmixResponse(
        contract_version=report.contract_version,
        query_spectrum_id=report.query_spectrum_id,
        baseline_applied=report.baseline_applied,
        grid_wavenumbers=report.grid_wavenumbers,
        observed=report.observed,
        fitted=report.fitted,
        residual=report.residual,
        components=[
            UnmixComponentOut(
                reference=_serialize(c.entry),
                weight=c.weight,
                raw_coefficient=c.raw_coefficient,
            )
            for c in report.components
        ],
        offset=report.offset,
        slope=report.slope,
        r_squared=report.r_squared,
        residual_norm_fraction=report.residual_norm_fraction,
        condition_number=report.condition_number,
        collinear_warnings=report.collinear_warnings,
    )


# --------------------------------------------------------------------------
# Contribute / moderate
# --------------------------------------------------------------------------


class ContributeReferenceRequest(BaseModel):
    spectrum_id: UUID
    compound_name: str = Field(min_length=1, max_length=200)
    chemical_formula: str | None = Field(default=None, max_length=120)
    cas_number: str | None = Field(default=None, max_length=20)
    mineral_name: str | None = Field(default=None, max_length=120)
    provenance_url: str | None = None
    notes: str | None = Field(default=None, max_length=1000)


@router.post(
    "/references", response_model=ReferenceEntryOut, status_code=status.HTTP_201_CREATED
)
def contribute_reference(
    body: ContributeReferenceRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> ReferenceEntryOut:
    """Promote one of your own published spectra into the shared library.

    Auto-approved: the entry is matchable immediately, at the `community` trust
    tier so it ranks below a curated standard at equal similarity and can be
    badged in the UI.
    """
    spectrum = db.get(Spectrum, body.spectrum_id)
    if spectrum is None or spectrum.owner_id != user.id:
        # 404 rather than 403, consistent with every other ownership check.
        raise HTTPException(status_code=404, detail="Spectrum not found.")
    if spectrum.state != SpectrumState.published:
        # Security, not policy: a reference's arrays are served to everyone who
        # matches against it, so admitting a draft would leak unpublished data.
        raise HTTPException(
            status_code=409,
            detail="Publish the spectrum before contributing it as a reference.",
        )
    if spectrum.modality != Modality.raman:
        raise HTTPException(
            status_code=422, detail="Only Raman spectra can be used as references."
        )

    existing = (
        db.query(ReferenceEntry)
        .filter(ReferenceEntry.spectrum_id == spectrum.id)
        .one_or_none()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="This spectrum is already a library reference."
        )

    entry = ReferenceEntry(
        spectrum_id=spectrum.id,
        compound_name=body.compound_name,
        chemical_formula=body.chemical_formula,
        cas_number=body.cas_number,
        mineral_name=body.mineral_name,
        source="user",
        source_id=None,
        source_dataset=None,
        provenance_url=body.provenance_url,
        trust_tier=ReferenceTrustTier.community,
        curation_status=ReferenceCurationStatus.approved,
        contributed_by=user.id,
        notes=body.notes,
    )
    db.add(entry)
    db.flush()

    # Warm inline so the entry is matchable on the very next request rather
    # than after the background warmer's next sweep.
    try:
        get_or_build_feature(spectrum, db)
        get_or_build_peak_index(spectrum, db)
    except Exception:  # noqa: BLE001 - an unindexable spectrum is still a valid entry
        pass

    db.commit()
    db.refresh(entry)
    return _serialize(entry, spectrum)


class ReferenceReportRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/references/{reference_id}/report", status_code=status.HTTP_204_NO_CONTENT)
def report_reference(
    reference_id: UUID,
    body: ReferenceReportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> Response:
    """Flag a reference as mislabelled.

    Deliberately does NOT remove it from matching — that is a moderator's call.
    Reporting raises a hand; it is not a veto.
    """
    entry = db.get(ReferenceEntry, reference_id)
    if entry is None or entry.curation_status == ReferenceCurationStatus.removed:
        raise HTTPException(status_code=404, detail="Reference not found.")
    entry.flagged_for_review = True
    entry.report_count = (entry.report_count or 0) + 1
    db.add(entry)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ReferenceModerationRequest(BaseModel):
    curation_status: Literal["approved", "demoted", "removed"]
    trust_tier: TrustTierLiteral | None = None
    note: str | None = Field(default=None, max_length=500)


@router.patch("/references/{reference_id}", response_model=ReferenceEntryOut)
def moderate_reference(
    reference_id: UUID,
    body: ReferenceModerationRequest,
    db: Session = Depends(get_db),
    moderator: User = Depends(get_current_moderator),
) -> ReferenceEntryOut:
    entry = db.get(ReferenceEntry, reference_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Reference not found.")
    entry.curation_status = ReferenceCurationStatus(body.curation_status)
    if body.trust_tier is not None:
        entry.trust_tier = ReferenceTrustTier(body.trust_tier)
    if body.note:
        entry.notes = body.note
    if body.curation_status != "approved":
        entry.flagged_for_review = False
    entry.curated_by = moderator.id
    entry.curated_at = datetime.now(timezone.utc)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _serialize(entry, db.get(Spectrum, entry.spectrum_id))
