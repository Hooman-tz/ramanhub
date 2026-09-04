"""Staged identification against the public reference library.

Three stages, each cheaper than the one it feeds:

1. **Prefilter (SQL).** The query's strongest bands are quantized to buckets and
   matched against the GIN-indexed `spectrum_peaks.binned_cm1` with `&&`. This
   turns "score the whole corpus" into "score a few hundred rows".
2. **Score (Python).** Cosine over the cached 512-point similarity vectors of
   the survivors only, reusing `raman_similarity` unchanged.
3. **Unmix (on demand).** Non-negative least squares over a caller-chosen set of
   references, run only when a single pure component doesn't explain the signal.

Stage 3 is a separate call rather than an automatic tail of stage 2 because it
is a different cost class (N+1 object-storage reads and a dense solve, versus an
index scan) and because deconvolution is a scientific claim: the component set
determines the answer, so a human should choose it.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import numpy as np
from scipy.optimize import nnls
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analysis.engine import _shared_grid, load_spectrum_arrays
from app.discovery.peak_index import get_or_build_peak_index
from app.discovery.raman_similarity import (
    FEATURE_VERSION,
    compatible,
    cosine_feature_similarity,
    get_or_build_feature,
)
from app.models.enums import (
    Modality,
    ReferenceCurationStatus,
    ReferenceTrustTier,
    SpectrumState,
)
from app.models.reference import ReferenceEntry
from app.models.similarity import SimilarityFeature
from app.models.spectrum import Spectrum
from app.models.spectrum_peaks import SpectrumPeaks
from app.processing.algorithms.registry import apply_step
from app.processing.peaks import (
    DEFAULT_BIN_TOLERANCE_CM1,
    PEAK_INDEX_VERSION,
    neighbor_bins,
)

MATCH_CONTRACT_VERSION = "library-match-1"

#: Below this top-1 cosine, a single pure reference is not a convincing
#: explanation and the UI offers deconvolution.
MIXTURE_SUSPECTED_BELOW = 0.90
#: A query band at least this tall (relative to the query's own strongest band)
#: that the winner cannot account for is itself evidence of a second component.
UNEXPLAINED_PEAK_REL_HEIGHT = 0.20
PEAK_TOLERANCE_CM1 = 8.0

NARROW_TOP_PEAKS = 3
WIDENED_TOLERANCE_CM1 = 20.0
#: How many peak-sharing candidates count as a confident narrow result. Small
#: on purpose. An earlier draft used 25 and was wrong: a query whose bands are
#: shared by only a handful of references would fail the floor and fall through
#: to a full-corpus scan — the exact cost the index exists to avoid. Finding
#: three genuine peak-sharing candidates is a *success*, not a shortfall.
MIN_CANDIDATES = 5
MAX_CANDIDATES = 2000

UNMIX_MAX_COMPONENTS = 6
#: Two design columns more similar than this are effectively the same compound
#: as far as the solver is concerned, and the split between them is arbitrary.
COLLINEAR_COSINE = 0.95


@dataclass
class MatchHit:
    entry: ReferenceEntry
    spectrum: Spectrum
    similarity: float
    overlap_fraction: float
    matched_peak_count: int
    unmatched_query_peaks_cm1: list[float]
    #: The candidate's own bands, needed by the set-cover suggestion pass.
    candidate_peaks_cm1: list[float]


@dataclass
class MatchReport:
    contract_version: str
    peak_index_version: str
    feature_version: str
    query_spectrum_id: UUID
    query_peaks: list[dict]
    primary_peak_cm1: float | None
    peak_to_background: float | None
    prefilter_stage: str
    candidates_screened: int
    candidates_scored: int
    hits: list[MatchHit]
    mixture_suspected: bool
    mixture_reason: str | None
    suggested_component_reference_ids: list[UUID]


@dataclass
class UnmixComponent:
    entry: ReferenceEntry
    weight: float
    raw_coefficient: float


@dataclass
class UnmixReport:
    contract_version: str
    query_spectrum_id: UUID
    baseline_applied: str
    grid_wavenumbers: list[float]
    observed: list[float]
    fitted: list[float]
    residual: list[float]
    components: list[UnmixComponent]
    offset: float
    slope: float
    r_squared: float
    residual_norm_fraction: float
    condition_number: float
    collinear_warnings: list[str]


# --------------------------------------------------------------------------
# Stage 1 — SQL prefilter
# --------------------------------------------------------------------------


def _reference_base_query(db: Session, *, exclude_spectrum_id: UUID | None):
    q = (
        db.query(SpectrumPeaks.spectrum_id)
        .join(ReferenceEntry, ReferenceEntry.spectrum_id == SpectrumPeaks.spectrum_id)
        .join(Spectrum, Spectrum.id == SpectrumPeaks.spectrum_id)
        .filter(
            SpectrumPeaks.peak_index_version == PEAK_INDEX_VERSION,
            SpectrumPeaks.qc_eligible.is_(True),
            SpectrumPeaks.modality == Modality.raman,
            ReferenceEntry.curation_status != ReferenceCurationStatus.removed,
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == "visible",
        )
    )
    if exclude_spectrum_id is not None:
        q = q.filter(SpectrumPeaks.spectrum_id != exclude_spectrum_id)
    return q


def prefilter_candidates(
    db: Session,
    *,
    peaks: list[dict],
    primary_cm1: float | None,
    query_wn_min: float,
    query_wn_max: float,
    trust_tiers: list[ReferenceTrustTier],
    exclude_spectrum_id: UUID | None = None,
    limit: int = MAX_CANDIDATES,
) -> tuple[list[UUID], str]:
    """Narrow the corpus by peak position, widening only when forced to.

    Returns `(spectrum_ids, stage)` where stage names which rung was used, so a
    slow low-quality match is visible in the response rather than mysterious.
    """

    def run(bins: list[int] | None) -> list[UUID]:
        q = _reference_base_query(db, exclude_spectrum_id=exclude_spectrum_id)
        q = q.filter(ReferenceEntry.trust_tier.in_(trust_tiers))
        # Range overlap: a reference that stops at 1200 cannot explain a band
        # at 1600, and scoring it wastes a vector dot product.
        q = q.filter(
            SpectrumPeaks.wavenumber_min <= query_wn_max,
            SpectrumPeaks.wavenumber_max >= query_wn_min,
        )
        if bins:
            # `.overlap()` emits `&&`, which is what the GIN array_ops index
            # serves. Ordering by intersection *cardinality* would need the
            # intarray extension, which the test harness does not create — so
            # shared-bin counting happens in Python over these bounded rows.
            q = q.filter(SpectrumPeaks.binned_cm1.overlap(bins))
        if primary_cm1 is not None:
            q = q.order_by(func.abs(SpectrumPeaks.primary_peak_cm1 - primary_cm1))
        return [row[0] for row in q.limit(limit).all()]

    narrow: list[UUID] = []
    if peaks:
        top = sorted(peaks, key=lambda p: -p["height"])[:NARROW_TOP_PEAKS]
        bins: list[int] = []
        for p in top:
            bins.extend(neighbor_bins(p["cm1"], tolerance_cm1=DEFAULT_BIN_TOLERANCE_CM1))
        narrow = run(sorted(set(bins)))
        if len(narrow) >= MIN_CANDIDATES:
            return narrow, "narrow"

    if primary_cm1 is not None:
        wide = run(sorted(set(neighbor_bins(primary_cm1, tolerance_cm1=WIDENED_TOLERANCE_CM1))))
        # Union, not replacement: a narrow hit is the most relevant thing we
        # have, and a wider sweep should add alternatives to it rather than
        # discard it.
        merged = list(dict.fromkeys(narrow + wide))
        if merged:
            return merged, "widened"
    elif narrow:
        return narrow, "narrow"

    # Last resort, reached only when the query shares no band with anything in
    # the library: scan the whole eligible corpus, capped. Slow, but a query
    # with an unusual or badly calibrated axis should still get an answer.
    return run(None), "full"


# --------------------------------------------------------------------------
# Stage 2 — score
# --------------------------------------------------------------------------


def _matched_peaks(
    query_peaks: list[dict], candidate_peaks: list[dict]
) -> tuple[int, list[float]]:
    """How many query bands the candidate accounts for, and which it misses."""
    cand = [p["cm1"] for p in candidate_peaks]
    matched = 0
    unmatched: list[float] = []
    for p in query_peaks:
        if any(abs(p["cm1"] - c) <= PEAK_TOLERANCE_CM1 for c in cand):
            matched += 1
        elif p.get("rel_height", 0.0) >= UNEXPLAINED_PEAK_REL_HEIGHT:
            unmatched.append(p["cm1"])
    return matched, unmatched


def match_against_library(
    target: Spectrum,
    db: Session,
    *,
    top_k: int = 10,
    trust_tiers: list[ReferenceTrustTier] | None = None,
    client_peaks_cm1: list[float] | None = None,
) -> MatchReport:
    tiers = trust_tiers or [ReferenceTrustTier.curated, ReferenceTrustTier.community]

    # The server always computes its own peaks. `client_peaks_cm1` is accepted
    # so the UI can say what it showed the user, and is used only to *widen*
    # the bucket set — never to narrow it, and never to replace these.
    peak_row = get_or_build_peak_index(target, db)
    query_peaks: list[dict] = list(peak_row.peaks or [])

    candidate_ids, stage = prefilter_candidates(
        db,
        peaks=query_peaks,
        primary_cm1=peak_row.primary_peak_cm1,
        query_wn_min=peak_row.wavenumber_min,
        query_wn_max=peak_row.wavenumber_max,
        trust_tiers=tiers,
        exclude_spectrum_id=target.id,
    )

    if client_peaks_cm1:
        extra_bins: list[int] = []
        for cm1 in client_peaks_cm1[:40]:
            extra_bins.extend(neighbor_bins(float(cm1)))
        if extra_bins:
            widened = _reference_base_query(db, exclude_spectrum_id=target.id)
            widened = widened.filter(
                ReferenceEntry.trust_tier.in_(tiers),
                SpectrumPeaks.binned_cm1.overlap(sorted(set(extra_bins))),
            ).limit(MAX_CANDIDATES)
            candidate_ids = list(dict.fromkeys(candidate_ids + [r[0] for r in widened.all()]))

    screened = len(candidate_ids)
    if not candidate_ids:
        return MatchReport(
            contract_version=MATCH_CONTRACT_VERSION,
            peak_index_version=PEAK_INDEX_VERSION,
            feature_version=FEATURE_VERSION,
            query_spectrum_id=target.id,
            query_peaks=query_peaks,
            primary_peak_cm1=peak_row.primary_peak_cm1,
            peak_to_background=peak_row.peak_to_background,
            prefilter_stage=stage,
            candidates_screened=0,
            candidates_scored=0,
            hits=[],
            mixture_suspected=False,
            mixture_reason=None,
            suggested_component_reference_ids=[],
        )

    target_feature = get_or_build_feature(target, db)

    features = {
        f.spectrum_id: f
        for f in db.query(SimilarityFeature)
        .filter(SimilarityFeature.spectrum_id.in_(candidate_ids))
        .all()
    }
    entries = {
        e.spectrum_id: e
        for e in db.query(ReferenceEntry)
        .filter(ReferenceEntry.spectrum_id.in_(candidate_ids))
        .all()
    }
    spectra = {
        s.id: s for s in db.query(Spectrum).filter(Spectrum.id.in_(candidate_ids)).all()
    }
    peak_rows = {
        p.spectrum_id: p
        for p in db.query(SpectrumPeaks)
        .filter(SpectrumPeaks.spectrum_id.in_(candidate_ids))
        .all()
    }

    hits: list[MatchHit] = []
    for spectrum_id in candidate_ids:
        feature = features.get(spectrum_id)
        entry = entries.get(spectrum_id)
        spectrum = spectra.get(spectrum_id)
        if feature is None or entry is None or spectrum is None:
            continue
        ok, overlap = compatible(target_feature, feature)
        if not ok:
            continue
        similarity = cosine_feature_similarity(target_feature, feature)
        cand_peaks = list((peak_rows.get(spectrum_id).peaks if peak_rows.get(spectrum_id) else []) or [])
        matched, unmatched = _matched_peaks(query_peaks, cand_peaks)
        hits.append(
            MatchHit(
                entry=entry,
                spectrum=spectrum,
                similarity=similarity,
                overlap_fraction=overlap,
                matched_peak_count=matched,
                unmatched_query_peaks_cm1=unmatched,
                candidate_peaks_cm1=[p["cm1"] for p in cand_peaks],
            )
        )

    # Round before the tier term or float noise at the 1e-9 level defeats the
    # tie-break every time. Trailing id makes the order total and deterministic.
    hits.sort(
        key=lambda h: (
            -round(h.similarity, 4),
            0 if h.entry.trust_tier == ReferenceTrustTier.curated else 1,
            -h.matched_peak_count,
            str(h.entry.spectrum_id),
        )
    )
    scored = len(hits)
    hits = hits[:top_k]

    mixture_suspected = False
    mixture_reason: str | None = None
    suggested: list[UUID] = []
    if hits:
        best = hits[0]
        if best.similarity < MIXTURE_SUSPECTED_BELOW:
            mixture_suspected = True
            mixture_reason = (
                f"Best single match explains only {best.similarity:.0%} of the signal."
            )
        elif best.unmatched_query_peaks_cm1:
            mixture_suspected = True
            positions = ", ".join(f"{c:.0f}" for c in best.unmatched_query_peaks_cm1[:4])
            mixture_reason = (
                f"Strong bands at {positions} cm-1 are not explained by the best match."
            )
        if mixture_suspected:
            suggested = _suggest_components(query_peaks, hits)

    return MatchReport(
        contract_version=MATCH_CONTRACT_VERSION,
        peak_index_version=PEAK_INDEX_VERSION,
        feature_version=FEATURE_VERSION,
        query_spectrum_id=target.id,
        query_peaks=query_peaks,
        primary_peak_cm1=peak_row.primary_peak_cm1,
        peak_to_background=peak_row.peak_to_background,
        prefilter_stage=stage,
        candidates_screened=screened,
        candidates_scored=scored,
        hits=hits,
        mixture_suspected=mixture_suspected,
        mixture_reason=mixture_reason,
        suggested_component_reference_ids=suggested,
    )


def _suggest_components(
    query_peaks: list[dict], hits: list[MatchHit], max_components: int = 4
) -> list[UUID]:
    """Greedy set cover: which few references between them explain the most bands.

    Pre-fills the deconvolution form. Greedy rather than exhaustive because the
    user edits the set anyway, and an approximate starting point they can see
    beats an optimal one they cannot.
    """
    significant = [
        p for p in query_peaks if p.get("rel_height", 0.0) >= UNEXPLAINED_PEAK_REL_HEIGHT
    ]
    if not significant:
        return [h.entry.id for h in hits[:2]]

    remaining = {round(p["cm1"], 2) for p in significant}
    chosen: list[UUID] = []
    pool = list(hits)

    while remaining and pool and len(chosen) < max_components:
        best_hit = None
        best_cover: set[float] = set()
        for hit in pool:
            covered = {
                cm1
                for cm1 in remaining
                if any(abs(cm1 - c) <= PEAK_TOLERANCE_CM1 for c in hit.candidate_peaks_cm1)
            }
            if len(covered) > len(best_cover):
                best_hit, best_cover = hit, covered
        if best_hit is None or not best_cover:
            break
        chosen.append(best_hit.entry.id)
        remaining -= best_cover
        pool.remove(best_hit)

    # Top up from the ranking so the form is never left with a single component.
    for hit in hits:
        if len(chosen) >= 2:
            break
        if hit.entry.id not in chosen:
            chosen.append(hit.entry.id)
    return chosen


# --------------------------------------------------------------------------
# Stage 3 — unmix
# --------------------------------------------------------------------------


@dataclass
class UnmixSolution:
    """The numeric result of a fit, independent of any database row."""

    weights: list[float]
    raw_coefficients: list[float]
    fitted: np.ndarray
    residual: np.ndarray
    offset: float
    slope: float
    r_squared: float
    residual_norm_fraction: float
    condition_number: float
    collinear_warnings: list[str]


def _prepare_reference_column(column: np.ndarray) -> np.ndarray:
    """Make one reference usable as a design column.

    Clipped non-negative because a reference cannot contribute negative
    intensity — baseline overshoot would otherwise let the solver cancel real
    signal — and L2-normalized so the reported fraction reflects composition
    rather than whichever reference happened to be measured at higher gain.
    """
    column = np.clip(np.asarray(column, dtype=float), 0.0, None)
    norm = float(np.linalg.norm(column))
    return column / norm if norm > 0 else column


def solve_unmix(
    grid: np.ndarray,
    observed: np.ndarray,
    columns: list[np.ndarray],
    names: list[str],
) -> UnmixSolution:
    """Non-negative least squares of `observed` onto `columns`, plus background.

    Kept free of `Session` and ORM types so the pitfalls it guards against —
    DC pedestals, gain differences, collinear polymorphs — are testable with
    synthetic arrays and no database.

    **What `weights` means.** Columns are L2-normalized before fitting, so a
    weight is the fraction of *spectral contribution* (in L2-energy terms), not
    a mixing ratio and emphatically not a concentration. Feeding in `0.7*A +
    0.3*B` returns `0.7||A|| / (0.7||A|| + 0.3||B||)`, which is 0.647 for a
    typical pair, not 0.700. That is the correct answer to the question this
    can actually answer: Raman cross-sections differ by orders of magnitude
    between compounds, so recovering a mole fraction from band areas alone is
    not possible without per-compound response factors. Callers must present
    these as "spectral weight".
    """
    if not columns:
        raise ValueError("At least one reference is required to deconvolve a spectrum.")

    observed = np.asarray(observed, dtype=float)
    n = observed.size

    # Two extra non-negative design columns soak up whatever the baseline step
    # left behind. Without them NNLS inflates the largest reference's weight to
    # absorb a DC pedestal and the composition is quietly wrong.
    const_col = np.ones(n)
    ramp_col = np.linspace(0.0, 1.0, n)
    design = np.column_stack(list(columns) + [const_col, ramp_col])

    coef, _rnorm = nnls(design, observed)
    component_coefs = coef[: len(columns)]
    offset = float(coef[len(columns)])
    slope = float(coef[len(columns) + 1])

    total = float(component_coefs.sum())
    if total <= 0.0:
        raise ValueError("No reference in the selected set explains any of this signal.")

    fitted = design @ coef
    residual = observed - fitted
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((observed - observed.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    obs_norm = float(np.linalg.norm(observed))
    residual_norm_fraction = (
        float(np.linalg.norm(residual)) / obs_norm if obs_norm > 0 else 0.0
    )

    # Collinearity is the pitfall that matters most for a mineral library:
    # polymorphs are near-duplicates, NNLS splits them arbitrarily, and the
    # residual still looks excellent. Surface it rather than hide it.
    warnings: list[str] = []
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            ni = float(np.linalg.norm(columns[i]))
            nj = float(np.linalg.norm(columns[j]))
            if ni == 0 or nj == 0:
                continue
            cos = float(np.dot(columns[i], columns[j]) / (ni * nj))
            if cos > COLLINEAR_COSINE:
                left = names[i] if i < len(names) else f"component {i + 1}"
                right = names[j] if j < len(names) else f"component {j + 1}"
                warnings.append(
                    f"{left} and {right} are {cos:.0%} similar — "
                    "the split between them is not well determined."
                )

    try:
        condition_number = float(np.linalg.cond(design))
    except Exception:  # noqa: BLE001
        condition_number = 0.0
    if not np.isfinite(condition_number):
        condition_number = 0.0

    return UnmixSolution(
        weights=[float(c / total) for c in component_coefs],
        raw_coefficients=[float(c) for c in component_coefs],
        fitted=fitted,
        residual=residual,
        offset=offset,
        slope=slope,
        r_squared=r_squared,
        residual_norm_fraction=residual_norm_fraction,
        condition_number=condition_number,
        collinear_warnings=warnings,
    )


def _baseline_corrected(x: np.ndarray, y: np.ndarray, mode: str) -> np.ndarray:
    if mode != "als":
        return y
    try:
        _wn, corrected = apply_step("raman.baseline.als", x, y, {})
        return corrected
    except Exception:  # noqa: BLE001 - a failed baseline is not a failed fit
        return y


def unmix(
    target: Spectrum,
    references: list[tuple[ReferenceEntry, Spectrum]],
    db: Session,
    *,
    grid_points: int = 512,
    baseline: str = "als",
) -> UnmixReport:
    """Fit the query as a non-negative combination of chosen references.

    What comes back are *spectral contribution weights*, not concentrations:
    Raman cross-sections differ by orders of magnitude between compounds, so a
    50/50 weight is not a 50/50 mixture. Callers must not relabel them.
    """
    if not references:
        raise ValueError("At least one reference is required to deconvolve a spectrum.")
    if len(references) > UNMIX_MAX_COMPONENTS:
        raise ValueError(
            f"At most {UNMIX_MAX_COMPONENTS} components can be fitted at once."
        )

    target_x, target_y = load_spectrum_arrays(target, db)
    arrays: list[tuple[np.ndarray, np.ndarray]] = [(target_x, target_y)]
    for _entry, spectrum in references:
        arrays.append(load_spectrum_arrays(spectrum, db))

    # Raises a human-readable ValueError on <80% overlap, which the router
    # turns into a 422 rather than a 500.
    grid, matrix = _shared_grid(arrays, grid_points)

    observed = _baseline_corrected(grid, matrix[0], baseline)
    columns = [
        _prepare_reference_column(_baseline_corrected(grid, row, baseline))
        for row in matrix[1:]
    ]
    names = [entry.compound_name for entry, _spectrum in references]
    solution = solve_unmix(grid, observed, columns, names)

    components = [
        UnmixComponent(
            entry=entry,
            weight=solution.weights[i],
            raw_coefficient=solution.raw_coefficients[i],
        )
        for i, (entry, _spectrum) in enumerate(references)
    ]

    return UnmixReport(
        contract_version=MATCH_CONTRACT_VERSION,
        query_spectrum_id=target.id,
        baseline_applied=baseline,
        grid_wavenumbers=[float(v) for v in grid],
        observed=[float(v) for v in observed],
        fitted=[float(v) for v in solution.fitted],
        residual=[float(v) for v in solution.residual],
        components=components,
        offset=solution.offset,
        slope=solution.slope,
        r_squared=solution.r_squared,
        residual_norm_fraction=solution.residual_norm_fraction,
        condition_number=solution.condition_number,
        collinear_warnings=solution.collinear_warnings,
    )
