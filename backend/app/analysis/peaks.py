"""Peak detection: find Raman bands and characterize them.

Built on `scipy.signal.find_peaks` + `peak_widths` (scipy is already a
dependency — no new package needed).

Why prominence is the primary control rather than absolute height: Raman
spectra sit on wildly different intensity scales (counts vs. counts/second
vs. a normalized 0-1 axis after SNV), so an absolute height threshold is
meaningless across submissions, while prominence — how far a peak stands
out from the surrounding baseline — is comparable. Callers that genuinely
want an absolute cut can still pass `min_height`.

The prominence default is expressed as a *fraction of the spectrum's
intensity range* rather than an absolute number, for the same reason.

A fraction-of-range threshold alone is not enough, though: on a noisy
spectrum whose bands are weak, 5% of the range sits *below* the noise, and
the detector happily returns fifty noise wiggles as "peaks". So the
effective threshold is `max(fraction x range, noise_multiple x sigma)`,
where sigma is estimated from the data (see `estimate_noise_sigma`). On a
clean spectrum the noise term vanishes and the fraction governs; on a noisy
one the noise term takes over. That combination is what makes "detect peaks"
survive as a one-click action on an arbitrary uploaded file, which is the
point.

FWHM is reported in cm-1 by converting scipy's width-in-samples using the
local wavenumber spacing, so the number means something physical on a
non-uniform axis instead of being a sample count.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import find_peaks, peak_widths

VERSION = "1.0.0"

PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "prominence_fraction": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "default": 0.05,
            "title": "Minimum prominence",
            "description": "As a fraction of the spectrum's intensity range. Lower finds more, "
            "smaller peaks. Scale-independent, so it works on raw counts and normalized data "
            "alike.",
        },
        "min_distance_cm1": {
            "type": "number",
            "minimum": 0,
            "default": 0.0,
            "title": "Minimum peak separation (cm-1)",
            "description": "Suppresses peaks closer together than this. 0 disables.",
        },
        "min_height": {
            "type": ["number", "null"],
            "default": None,
            "title": "Minimum absolute height",
            "description": "Optional absolute intensity floor. Usually leave empty and use "
            "prominence instead — absolute heights are not comparable across spectra.",
        },
        "noise_multiple": {
            "type": "number",
            "minimum": 0,
            "default": 6.0,
            "title": "Noise rejection",
            "description": "A peak must stand this many noise standard deviations above the "
            "baseline. Raise it if noise is being reported as bands; lower it to chase very "
            "weak peaks. 0 disables noise-based rejection entirely.",
        },
        "max_peaks": {
            "type": "integer",
            "minimum": 1,
            "maximum": 500,
            "default": 50,
            "title": "Maximum peaks returned",
            "description": "Keeps the strongest N by prominence.",
        },
    },
}

DEFAULTS = {
    "prominence_fraction": 0.05,
    "min_distance_cm1": 0.0,
    "min_height": None,
    "noise_multiple": 6.0,
    "max_peaks": 50,
}


@dataclass(frozen=True)
class Peak:
    """One detected band. `index` is into the (ascending-sorted) input
    arrays, kept so the frontend can mark the exact sample on the chart."""

    index: int
    wavenumber: float
    intensity: float
    prominence: float
    fwhm_cm1: float | None
    area: float

    def as_dict(self) -> dict:
        return asdict(self)


def estimate_noise_sigma(intensities: np.ndarray) -> float:
    """Estimate the point-to-point noise standard deviation, robustly.

    Deliberately NOT `std(diff(y))` — the estimator `app.spectra_io.
    compute_snr` uses. That one is fine as a relative SNR proxy, but as an
    absolute threshold it fails badly on a clean spectrum: the steep flanks
    of a real Raman band dominate the standard deviation, so a noiseless
    spectrum reports large "noise" and its own peaks get rejected.

    Median absolute deviation fixes that. Most points of a Raman spectrum
    are flat baseline and only a few sit on a peak flank, so the median is
    unmoved by the bands themselves. 1.4826 rescales MAD to a Gaussian
    sigma; dividing by sqrt(2) undoes the variance doubling that
    differencing introduces (var(y[i+1] - y[i]) = 2 x var(noise)).
    """
    if intensities.size < 3:
        return 0.0
    deltas = np.diff(intensities)
    mad = float(np.median(np.abs(deltas - np.median(deltas))))
    return 1.4826 * mad / np.sqrt(2.0)


def _mean_spacing(x: np.ndarray) -> float:
    """Average |delta| between neighbouring wavenumbers. Used to convert
    scipy's sample-based widths and distances into cm-1."""
    if x.size < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(x))))


def detect_peaks(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    prominence_fraction: float = 0.05,
    min_distance_cm1: float = 0.0,
    min_height: float | None = None,
    noise_multiple: float = 6.0,
    max_peaks: int = 50,
) -> list[Peak]:
    """Detect and characterize peaks. Returns them sorted by wavenumber
    ascending (reading order for a spectroscopist), after truncating to the
    `max_peaks` most prominent.

    Returns `[]` rather than raising for degenerate input (too few points, a
    perfectly flat spectrum) — "no peaks" is the correct answer there, and a
    bulk caller shouldn't have to guard every spectrum.
    """
    x = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if x.size != y.size:
        raise ValueError("detect_peaks: wavenumber and intensity arrays must match in length")
    if x.size < 3:
        return []

    # scipy assumes an ascending axis; vendors write either direction.
    order = np.argsort(x)
    x, y = x[order], y[order]

    intensity_range = float(np.max(y) - np.min(y))
    if intensity_range <= 0:
        return []

    prominence = max(prominence_fraction, 0.0) * intensity_range
    # Noise floor: a band has to clear the noise, not just a fixed slice of
    # the range. Without this the default finds tens of noise wiggles on any
    # real spectrum whose bands aren't unusually strong.
    if noise_multiple > 0:
        prominence = max(prominence, noise_multiple * estimate_noise_sigma(y))
    # A prominence of exactly 0 makes find_peaks return every local wiggle,
    # including single-sample noise. Floor it at a small epsilon of the
    # range so "0" degrades to "very sensitive" rather than "unusable".
    prominence = max(prominence, intensity_range * 1e-6)

    spacing = _mean_spacing(x)
    distance = None
    if min_distance_cm1 > 0 and spacing > 0:
        # find_peaks wants a distance in samples, and requires >= 1.
        distance = max(round(min_distance_cm1 / spacing), 1)

    indices, properties = find_peaks(
        y,
        prominence=prominence,
        distance=distance,
        height=min_height,
    )
    if indices.size == 0:
        return []

    prominences = np.asarray(properties["prominences"], dtype=float)

    # Width at half prominence (rel_height=0.5) — the standard FWHM
    # convention, and measured from the peak's own base rather than from
    # zero, so a band riding on a residual baseline still reports a sane
    # width.
    widths_samples, _, _, _ = peak_widths(y, indices, rel_height=0.5)
    widths_cm1 = widths_samples * spacing if spacing > 0 else np.full_like(widths_samples, np.nan)

    peaks = [
        Peak(
            index=int(idx),
            wavenumber=float(x[idx]),
            intensity=float(y[idx]),
            prominence=float(prom),
            fwhm_cm1=(None if not np.isfinite(width) else float(width)),
            # Gaussian-equivalent integrated intensity from height and FWHM.
            # Cheap, and far more stable than trapezoid-integrating an
            # arbitrary window whose bounds would themselves need choosing.
            area=(
                0.0
                if not np.isfinite(width)
                else float(prom * width * 1.0644670194312942)  # sqrt(pi / (4 ln2))
            ),
        )
        for idx, prom, width in zip(indices, prominences, widths_cm1, strict=True)
    ]

    if len(peaks) > max_peaks:
        peaks = sorted(peaks, key=lambda p: p.prominence, reverse=True)[:max_peaks]

    return sorted(peaks, key=lambda p: p.wavenumber)
