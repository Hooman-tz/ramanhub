"""Module 4c: analysis endpoints — peak detection, PCA, HCA.

Mounted with no prefix. Routes:
`GET  /spectra/{spectrum_id}/peaks`
`POST /analysis/pca`
`POST /analysis/hca`
`GET  /analysis/catalog`

Access control note, and the reason the multi-spectrum endpoints look
repetitive: every spectrum in a `spectrum_ids` list is resolved and checked
**individually** through `require_owner_or_public`. A bulk endpoint that
checked only the first, or that trusted the caller because they own *one* of
the inputs, would be a way to read other people's draft data — the exact
row-level leak the architecture doc calls "the one bug that would matter
most". Any future bulk endpoint must follow the same pattern.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.analysis import hca as hca_mod
from app.analysis import pca as pca_mod
from app.analysis import peaks as peaks_mod
from app.analysis.common_grid import IncompatibleSpectraError
from app.analysis.hca import InvalidLinkageError
from app.auth.deps import get_current_user_optional
from app.db.session import get_db
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_owner_or_public
from app.spectrum_access import load_raw_arrays, load_spectrum_arrays

router = APIRouter(tags=["analysis"])

# Upper bound on a single multivariate request. PCA/HCA are synchronous and
# load every member spectrum's array, so this is what stops one request from
# pinning the single FastAPI instance the Scaling Posture assumes.
MAX_SPECTRA_PER_ANALYSIS = 200


class PeakOut(BaseModel):
    index: int
    wavenumber: float
    intensity: float
    prominence: float
    fwhm_cm1: float | None
    area: float


class PeakDetectionResponse(BaseModel):
    spectrum_id: UUID
    peaks: list[PeakOut]
    params: dict
    version: str
    stage: str
    """Which arrays the peaks were found on — "processed" or "raw". Recorded
    so a peak list quoted in a Finding can't be misread as applying to the
    other one."""


class MultiSpectrumRequest(BaseModel):
    spectrum_ids: list[UUID] = Field(min_length=2, max_length=MAX_SPECTRA_PER_ANALYSIS)
    raw: bool = False


class PcaRequest(MultiSpectrumRequest):
    n_components: int = Field(default=3, ge=2, le=10)
    mean_center: bool = True
    scale: bool = False


class PcaResponse(BaseModel):
    spectrum_ids: list[UUID]
    """Echoed back in the same row order as `scores`, so the frontend can
    label each point without assuming the request order survived."""
    wavenumbers: list[float]
    scores: list[list[float]]
    loadings: list[list[float]]
    explained_variance_ratio: list[float]
    n_components: int
    n_spectra: int
    version: str


class HcaRequest(MultiSpectrumRequest):
    metric: str = "correlation"
    method: str = "average"
    n_clusters: int | None = Field(default=None, ge=2, le=50)


class HcaResponse(BaseModel):
    spectrum_ids: list[UUID]
    linkage_matrix: list[list[float]]
    leaf_order: list[int]
    labels: list[int] | None
    distances: list[float]
    n_spectra: int
    version: str


class AnalysisCatalog(BaseModel):
    """Mirrors `GET /processing/algorithms`: the frontend renders analysis
    parameter inputs from this rather than hardcoding them, so adding a
    parameter server-side surfaces in the UI without a frontend change."""

    peaks: dict
    pca: dict
    hca: dict


def _resolve_accessible(
    spectrum_ids: list[UUID], user: User | None, db: Session
) -> list[Spectrum]:
    """Load every requested spectrum, 404ing on unknown IDs and enforcing
    the owner-or-public rule on each one individually. Preserves the
    caller's ordering; rejects duplicates, which would otherwise show up as
    two identical points in a PCA plot and a zero-distance pair in HCA."""
    if len(set(spectrum_ids)) != len(spectrum_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Duplicate spectrum IDs in request.",
        )

    resolved: list[Spectrum] = []
    for spectrum_id in spectrum_ids:
        spectrum = db.get(Spectrum, spectrum_id)
        if spectrum is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Spectrum {spectrum_id} not found"
            )
        require_owner_or_public(spectrum, user)
        resolved.append(spectrum)
    return resolved


def _load_arrays(spectra: list[Spectrum], raw: bool, db: Session):
    loader = load_raw_arrays if raw else load_spectrum_arrays
    return [loader(spectrum, db) for spectrum in spectra]


@router.get("/analysis/catalog", response_model=AnalysisCatalog)
def analysis_catalog() -> AnalysisCatalog:
    return AnalysisCatalog(
        peaks={
            "version": peaks_mod.VERSION,
            "param_schema": peaks_mod.PARAM_SCHEMA,
            "defaults": peaks_mod.DEFAULTS,
        },
        pca={
            "version": pca_mod.VERSION,
            "param_schema": pca_mod.PARAM_SCHEMA,
            "defaults": pca_mod.DEFAULTS,
        },
        hca={
            "version": hca_mod.VERSION,
            "param_schema": hca_mod.PARAM_SCHEMA,
            "defaults": hca_mod.DEFAULTS,
        },
    )


@router.get("/spectra/{spectrum_id}/peaks", response_model=PeakDetectionResponse)
def get_spectrum_peaks(
    spectrum_id: UUID,
    prominence_fraction: float = Query(0.05, ge=0.0, le=1.0),
    min_distance_cm1: float = Query(0.0, ge=0.0),
    min_height: float | None = Query(None),
    max_peaks: int = Query(50, ge=1, le=500),
    raw: bool = Query(False, description="Detect on the unprocessed spectrum instead."),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> PeakDetectionResponse:
    """Detect peaks on a spectrum's current processed output (or its raw
    data with `?raw=true`).

    Peaks are computed on demand rather than stored: they're a pure function
    of the arrays plus these parameters, and the arrays themselves are
    already cached by `hash(raw_file_id + ledger)`. Persisting them would add
    a second thing to invalidate whenever a ledger changes.
    """
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)

    wavenumbers, intensities = (
        load_raw_arrays(spectrum, db) if raw else load_spectrum_arrays(spectrum, db)
    )

    params = {
        "prominence_fraction": prominence_fraction,
        "min_distance_cm1": min_distance_cm1,
        "min_height": min_height,
        "max_peaks": max_peaks,
    }
    detected = peaks_mod.detect_peaks(wavenumbers, intensities, **params)

    return PeakDetectionResponse(
        spectrum_id=spectrum.id,
        peaks=[PeakOut(**peak.as_dict()) for peak in detected],
        params=params,
        version=peaks_mod.VERSION,
        stage="raw" if raw else ("processed" if spectrum.current_ledger_id else "raw"),
    )


@router.post("/analysis/pca", response_model=PcaResponse)
def post_pca(
    payload: PcaRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> PcaResponse:
    """PCA across two or more spectra, aligned onto their shared wavenumber
    range first (see `app.analysis.common_grid`)."""
    spectra = _resolve_accessible(payload.spectrum_ids, user, db)
    arrays = _load_arrays(spectra, payload.raw, db)

    try:
        result = pca_mod.run_pca(
            arrays,
            n_components=payload.n_components,
            mean_center=payload.mean_center,
            scale=payload.scale,
        )
    except IncompatibleSpectraError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return PcaResponse(
        spectrum_ids=[s.id for s in spectra],
        wavenumbers=result.wavenumbers,
        scores=result.scores,
        loadings=result.loadings,
        explained_variance_ratio=result.explained_variance_ratio,
        n_components=result.n_components,
        n_spectra=result.n_spectra,
        version=pca_mod.VERSION,
    )


@router.post("/analysis/hca", response_model=HcaResponse)
def post_hca(
    payload: HcaRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> HcaResponse:
    """Hierarchical clustering across two or more spectra."""
    spectra = _resolve_accessible(payload.spectrum_ids, user, db)
    arrays = _load_arrays(spectra, payload.raw, db)

    try:
        result = hca_mod.run_hca(
            arrays,
            metric=payload.metric,
            method=payload.method,
            n_clusters=payload.n_clusters,
        )
    except (IncompatibleSpectraError, InvalidLinkageError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return HcaResponse(
        spectrum_ids=[s.id for s in spectra],
        linkage_matrix=result.linkage_matrix,
        leaf_order=result.leaf_order,
        labels=result.labels,
        distances=result.distances,
        n_spectra=result.n_spectra,
        version=hca_mod.VERSION,
    )
