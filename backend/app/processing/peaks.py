"""Deterministic Raman peak detection.

Pure signal processing: numpy and scipy only, no `Session`, no models, no HTTP.
It lives in the processing unit because that is what survives the Go migration,
and because peak finding is DSP by any reading of the word.

It is deliberately *not* an entry in `app.processing.algorithms.registry`. An
`AlgorithmSpec.apply` must return intensities (or an (x, y) pair) so it can be
replayed as a ledger step; peak finding returns a list of features about a
spectrum, not a transformation of it. Putting it in the catalog would offer
users a "processing step" that cannot be applied.

Versioned exactly like `raman_similarity.FEATURE_VERSION`: any change to the
detection maths must bump `PEAK_INDEX_VERSION`, which invalidates every cached
row rather than leaving a corpus indexed by two different algorithms.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Sequence

import numpy as np
from scipy.signal import find_peaks, peak_widths

PEAK_INDEX_VERSION = "raman-peaks-1"

#: Width of one prefilter bucket, in cm-1. Small enough that two genuinely
#: different bands rarely share a bucket, large enough to absorb ordinary
#: instrument calibration drift between labs.
PEAK_BIN_WIDTH_CM1 = 4.0
MAX_INDEXED_PEAKS = 20
#: Prominence floor, in units of the spectrum's own robust noise sigma.
#: Empirically tuned: at 3 sigma a clean three-band synthetic returns 20 peaks
#: (17 of them noise) and pure noise returns 20; at 6 sigma the same synthetic
#: returns exactly its 3 bands and pure noise returns ~1. Because the threshold
#: scales with measured noise, a genuine minor band at 3% of the primary is
#: still recovered on high-SNR data and only dropped when it is statistically
#: indistinguishable from noise. Junk peaks matter more than usual here: they
#: land in `binned_cm1`, and a library entry with junk bins overlaps every
#: query, which is exactly what the prefilter exists to prevent.
MIN_PROMINENCE_SIGMA = 6.0
MIN_PEAK_DISTANCE_CM1 = 6.0
DEFAULT_BASELINE_WINDOW = 101
#: Half-width of the bin fan-out used when querying, in cm-1.
DEFAULT_BIN_TOLERANCE_CM1 = 8.0


@dataclass(frozen=True)
class Peak:
    """One detected band."""

    cm1: float
    height: float
    #: Height relative to the strongest peak, in (0, 1]. Lets a caller talk
    #: about "a major unexplained band" without knowing absolute units.
    rel_height: float
    prominence: float
    fwhm: float | None
    snr: float

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PeakProfile:
    """Every peak in one spectrum, plus the background it was measured against."""

    peaks: list[Peak]
    primary_peak_cm1: float | None
    primary_peak_prominence: float | None
    peak_to_background: float
    baseline_level: float
    noise_sigma: float


def estimate_baseline(y: np.ndarray, window: int = DEFAULT_BASELINE_WINDOW) -> np.ndarray:
    """A rolling low percentile — the slow-varying floor under the bands.

    Raman spectra routinely sit on a fluorescence ramp an order of magnitude
    taller than the bands themselves. Ranking raw intensity on such a spectrum
    returns the top of the ramp, not the strongest band, so the background has
    to come off before anything is called a "peak".

    A percentile rather than a minimum: a rolling minimum latches onto negative
    noise excursions and produces a floor that is systematically too low.
    """
    n = y.size
    if n == 0:
        return np.zeros(0)
    window = max(3, min(int(window) | 1, n if n % 2 else n - 1))
    if window < 3:
        return np.full(n, float(np.min(y)))

    half = window // 2
    padded = np.pad(y, half, mode="edge")
    strides = np.lib.stride_tricks.sliding_window_view(padded, window)
    return np.percentile(strides, 10, axis=-1)


def estimate_noise(residual: np.ndarray) -> float:
    """Robust sigma via the median absolute deviation.

    MAD rather than std: std over a spectrum is dominated by the peaks, which
    is precisely the signal we are trying to measure *against*, so it would
    scale the detection threshold with the thing being detected.
    """
    if residual.size == 0:
        return 0.0
    mad = float(np.median(np.abs(residual - np.median(residual))))
    sigma = 1.4826 * mad
    if sigma > 0.0:
        return sigma
    # A perfectly flat or quantized trace has zero MAD. Fall back to std so a
    # synthetic/noiseless spectrum still yields a usable threshold instead of
    # dividing by zero downstream.
    return float(np.std(residual)) or 0.0


def _refine_position(x: np.ndarray, y: np.ndarray, index: int) -> float:
    """Sub-sample peak position by fitting a parabola to three points.

    Without this, every peak position is quantized to the sampling grid, which
    can be coarser than the 4 cm-1 bin width — so a band would land in one bin
    or its neighbour depending on where the detector happened to sample it.
    """
    if index <= 0 or index >= x.size - 1:
        return float(x[index])
    y0, y1, y2 = float(y[index - 1]), float(y[index]), float(y[index + 1])
    denom = y0 - 2.0 * y1 + y2
    if denom == 0.0:
        return float(x[index])
    # Offset in samples from the centre point, clamped: a parabola through
    # near-collinear points can extrapolate absurdly far.
    delta = 0.5 * (y0 - y2) / denom
    if not np.isfinite(delta) or abs(delta) > 1.0:
        return float(x[index])
    spacing = float(x[index + 1] - x[index - 1]) / 2.0
    return float(x[index]) + delta * spacing


def detect_peaks(
    x: np.ndarray,
    y: np.ndarray,
    *,
    min_prominence_sigma: float = MIN_PROMINENCE_SIGMA,
    min_distance_cm1: float = MIN_PEAK_DISTANCE_CM1,
    max_peaks: int = MAX_INDEXED_PEAKS,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
) -> PeakProfile:
    """Find bands in a canonical Raman spectrum, strongest first."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size != y.size:
        raise ValueError("Wavenumber and intensity arrays must be the same length.")
    if x.size < 5:
        return PeakProfile([], None, None, 0.0, 0.0, 0.0)

    baseline = estimate_baseline(y, baseline_window)
    corrected = y - baseline
    sigma = estimate_noise(corrected)
    baseline_level = float(np.median(baseline))

    if sigma <= 0.0:
        return PeakProfile([], None, None, 0.0, baseline_level, 0.0)

    # `find_peaks` counts distance in samples, so convert from cm-1 using the
    # median step — spectra are not guaranteed to be evenly sampled.
    steps = np.diff(x)
    median_step = float(np.median(np.abs(steps))) if steps.size else 0.0
    distance = max(1, int(round(min_distance_cm1 / median_step))) if median_step > 0 else 1

    threshold = min_prominence_sigma * sigma
    indices, props = find_peaks(corrected, prominence=threshold, distance=distance)
    if indices.size == 0:
        return PeakProfile([], None, None, 0.0, baseline_level, sigma)

    prominences = np.asarray(props["prominences"], dtype=float)
    heights = corrected[indices]

    try:
        widths_samples = peak_widths(corrected, indices, rel_height=0.5)[0]
        widths = widths_samples * median_step if median_step > 0 else None
    except Exception:  # noqa: BLE001 - width estimation is cosmetic, never fatal
        widths = None

    strongest = float(np.max(heights))
    if strongest <= 0.0:
        return PeakProfile([], None, None, 0.0, baseline_level, sigma)

    peaks = [
        Peak(
            cm1=_refine_position(x, corrected, int(idx)),
            height=float(heights[i]),
            rel_height=float(heights[i] / strongest),
            prominence=float(prominences[i]),
            fwhm=float(widths[i]) if widths is not None else None,
            snr=float(prominences[i] / sigma),
        )
        for i, idx in enumerate(indices)
    ]
    peaks.sort(key=lambda p: (-p.height, p.cm1))
    peaks = peaks[:max_peaks]

    primary = peaks[0]
    # Guard the zero-baseline case rather than emitting `inf` into JSON, which
    # is not valid JSON and would fail serialization at the API edge.
    denominator = max(abs(baseline_level), sigma)
    ptb = float(primary.height / denominator) if denominator > 0 else 0.0

    return PeakProfile(
        peaks=peaks,
        primary_peak_cm1=primary.cm1,
        primary_peak_prominence=primary.prominence,
        peak_to_background=ptb,
        baseline_level=baseline_level,
        noise_sigma=sigma,
    )


def bin_peak(cm1: float, *, bin_width: float = PEAK_BIN_WIDTH_CM1) -> int:
    return int(np.floor(cm1 / bin_width))


def bin_peaks(
    peaks: Sequence[Peak], *, bin_width: float = PEAK_BIN_WIDTH_CM1
) -> list[int]:
    """The deduped, sorted bucket ids stored in the GIN-indexed array column."""
    return sorted({bin_peak(p.cm1, bin_width=bin_width) for p in peaks})


def neighbor_bins(
    cm1: float,
    *,
    tolerance_cm1: float = DEFAULT_BIN_TOLERANCE_CM1,
    bin_width: float = PEAK_BIN_WIDTH_CM1,
) -> list[int]:
    """Every bucket within `tolerance_cm1` of a position.

    Query-side counterpart to `bin_peaks`. A single bucket lookup would miss a
    band that fell just the other side of a bucket edge, so the query fans out
    and the exact position is re-checked later against the peak list.
    """
    low = bin_peak(cm1 - tolerance_cm1, bin_width=bin_width)
    high = bin_peak(cm1 + tolerance_cm1, bin_width=bin_width)
    return list(range(low, high + 1))
