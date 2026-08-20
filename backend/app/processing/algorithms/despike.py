"""Cosmic-ray spike removal.

Cosmic rays hit the detector as one- or two-pixel spikes that are enormous
relative to real Raman bands and, crucially, *narrow*: they survive no
smoothing and corrupt every downstream step (a single spike dominates SNV's
variance, drags a polynomial baseline upward, and destroys peak-normalized
comparisons). They must therefore be removed first, before any other step.

## Detection

The starting point is Whitaker & Hayes (2018), "A simple algorithm for
despiking Raman spectra" (Chemometrics and Intelligent Laboratory Systems,
179, 82-84): score the *first difference* of the spectrum with a modified
Z-score built on the median and median absolute deviation (MAD). Working on
differences amplifies single-point discontinuities while flattening the
broad structure of real bands, and the median/MAD pair keeps a large spike
from inflating the very statistics used to detect it.

That Z-score alone is not sufficient, and this implementation adds two
further criteria, both required:

1. **Sign reversal within a few points.** A cosmic ray goes sharply up and
   comes straight back down; the flank of a real band produces a long run of
   same-signed differences. Requiring a matching opposite-signed jump within
   `max_width` points is what lets a spike be found even when it lands on a
   band's flank, where a plain run-length test would throw both away
   together.
2. **Prominence relative to the spectrum's own dynamic range.** On clean,
   low-noise data the MAD is set by the noise floor alone, so a band's own
   curvature at its apex scores in the dozens and a purely noise-relative
   test flags real peaks. Requiring the candidate to stand at least
   `min_prominence_ratio` of the spectrum's robust dynamic range above its
   surroundings restores a physical scale to the decision.

Known limitation, stated plainly: a genuine Raman band only two or three
points wide *and* comparable in height to the strongest band in the spectrum
is indistinguishable from a cosmic ray by these criteria, and will be
removed. Such a band is badly undersampled to begin with; if that is the
data, lower `max_width` to 1 or skip this step.

## Repair

Flagged points are replaced by linear interpolation between the nearest
unflagged neighbours on each side, which preserves the local slope — the
right behaviour when the spike sat on a band's flank, where replacing it
with a neighbourhood mean would visibly notch the flank instead.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import medfilt

STEP_TYPE = "raman.despike"
VERSION = "1.0.0"
LABEL = "Despike (cosmic ray removal)"
CATEGORY = "despiking"
DESCRIPTION = (
    "Removes narrow cosmic-ray spikes — points that jump sharply up and straight back down, "
    "far above the spectrum's own dynamic range — and repairs them by interpolating across. "
    "Run this first: spikes corrupt every subsequent step."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "threshold": {
            "type": "number",
            "default": 6.0,
            "minimum": 0,
            "title": "Z-score threshold",
            "description": "How far above the noise a jump must score to be a candidate. "
            "6 is the published default; lower flags more.",
        },
        "max_width": {
            "type": "integer",
            "default": 3,
            "minimum": 1,
            "title": "Max spike width (points)",
            "description": "Anything wider than this is treated as real signal, not a cosmic ray.",
        },
        "min_prominence_ratio": {
            "type": "number",
            "default": 0.2,
            "minimum": 0,
            "title": "Min prominence (fraction of dynamic range)",
            "description": "A candidate must stand this far above its surroundings, relative to "
            "the spectrum's own peak-to-median range. Set to 0 to disable.",
        },
    },
}

# MAD -> standard-deviation scaling for a normal distribution (Iglewicz &
# Hoaglin): 0.6745 is the 0.75 quantile of the standard normal, so
# 0.6745 * (x - median) / MAD is on the same scale as a plain Z-score.
_MAD_SCALE = 0.6745

# A cosmic ray's rise and fall are the same event, so the two jumps should
# be comparable in size. Without this, a scan walking a band's flank happily
# pairs one of the flank's own modest opposite-signed differences with the
# spike's enormous one, producing a body that brackets the spike instead of
# covering it — and the spike survives. Requiring the smaller jump to be at
# least this fraction of the larger rejects those lopsided pairs.
_MIN_JUMP_BALANCE = 0.2


def modified_zscore(values: np.ndarray) -> np.ndarray:
    """Median/MAD-based Z-score. Returns all-zeros when the MAD is zero (a
    constant input has no outliers to find), rather than dividing by zero."""
    median = np.median(values)
    mad = np.median(np.abs(values - median))
    if mad == 0:
        return np.zeros_like(values)
    return _MAD_SCALE * (values - median) / mad


def _dynamic_range(spectrum: np.ndarray) -> float:
    """Robust peak-to-median height of the spectrum. Measured on a
    median-filtered copy so the spikes being hunted don't set the scale they
    are about to be judged against."""
    smooth = medfilt(spectrum, 5) if spectrum.size >= 5 else spectrum
    return float(np.percentile(smooth, 99) - np.median(smooth))


def _is_balanced(rise: float, fall: float) -> bool:
    magnitudes = (abs(float(rise)), abs(float(fall)))
    return min(magnitudes) >= _MIN_JUMP_BALANCE * max(magnitudes)


def find_spike_bodies(spectrum: np.ndarray, threshold: float, max_width: int) -> list[range]:
    """Return the index ranges of candidate spikes: a jump above `threshold`
    followed within `max_width` points by an opposite-signed jump of
    comparable size."""
    # np.diff shortens the array by one; prepending a zero realigns each
    # score with the point *after* the discontinuity, which is the spike.
    scores = modified_zscore(np.concatenate(([0.0], np.diff(spectrum))))
    extreme = np.abs(scores) > threshold

    bodies: list[range] = []
    start = 0
    while start < scores.size:
        if not extreme[start]:
            start += 1
            continue
        partner = next(
            (
                end
                for end in range(start + 1, min(start + max_width + 1, scores.size))
                if extreme[end]
                and np.sign(scores[end]) != np.sign(scores[start])
                and _is_balanced(scores[start], scores[end])
            ),
            None,
        )
        if partner is None:
            start += 1
            continue
        bodies.append(range(start, partner))
        start = partner + 1
    return bodies


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    """Return the spectrum with detected spikes interpolated over."""
    threshold = float(params.get("threshold", 6.0))
    max_width = int(params.get("max_width", 3))
    min_prominence_ratio = float(params.get("min_prominence_ratio", 0.2))
    if max_width < 1:
        raise ValueError("despike: max_width must be >= 1")

    x = np.asarray(spectrum, dtype=float)
    if x.size < 3:
        return x.copy()

    min_prominence = min_prominence_ratio * _dynamic_range(x)
    spikes = np.zeros(x.size, dtype=bool)
    for body in find_spike_bodies(x, threshold, max_width):
        left = x[body.start - 1] if body.start > 0 else x[body.stop]
        right = x[body.stop] if body.stop < x.size else x[body.start - 1]
        surroundings = (left + right) / 2
        prominence = float(np.abs(x[body.start : body.stop] - surroundings).max())
        if prominence >= min_prominence:
            spikes[body.start : body.stop] = True

    if not spikes.any():
        return x.copy()
    if spikes.all():
        # Nothing clean to interpolate from; leaving the data alone is
        # safer than inventing a replacement for all of it.
        return x.copy()

    cleaned = x.copy()
    indices = np.arange(x.size)
    cleaned[spikes] = np.interp(indices[spikes], indices[~spikes], x[~spikes])
    return cleaned
