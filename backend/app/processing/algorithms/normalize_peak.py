"""Peak normalization: scale so a chosen reference band has intensity 1.

This is the normalization Raman practitioners reach for most often when
they have an internal standard — a band known to be invariant across the
sample set (a substrate band, a solvent band, the 520 cm-1 silicon line).
Scaling to it converts every other band into a ratio against a physically
meaningful reference, which is what makes intensities comparable between
measurements rather than merely similar-looking.

Axis-aware because the reference band is specified in wavenumbers, not
sample index: the same `wavenumber` param must select the same physical band
regardless of the instrument's sampling grid. The band is located as the
maximum within `± tolerance` of the requested position rather than the exact
nearest point, since real peak centres shift by a few cm-1 between
instruments and calibrations.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.normalize.peak"
VERSION = "1.0.0"
LABEL = "Peak normalization"
CATEGORY = "normalization"
DESCRIPTION = (
    "Scales the spectrum so a chosen reference band (or the global maximum) equals 1 — "
    "the standard approach when an internal-standard band is available."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "wavenumber": {
            "type": "number",
            "minimum": 0,
            "title": "Reference band (cm-1)",
            "description": "Leave empty to normalize to the spectrum's global maximum.",
        },
        "tolerance": {
            "type": "number",
            "default": 10.0,
            "minimum": 0,
            "title": "Search window (± cm-1)",
            "description": "The maximum within this window of the requested position is used, "
            "which absorbs small calibration shifts between instruments.",
        },
    },
}


def apply(wavenumbers: np.ndarray, intensities: np.ndarray, **params):
    x = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if x.size != y.size:
        raise ValueError("normalize_peak: wavenumber and intensity arrays must match in length")
    if y.size == 0:
        raise ValueError("normalize_peak: empty spectrum")

    target = params.get("wavenumber")
    if target is None:
        reference = float(y.max())
    else:
        tolerance = abs(float(params.get("tolerance", 10.0)))
        window = np.abs(x - float(target)) <= tolerance
        if not window.any():
            raise ValueError(
                f"normalize_peak: no points within ±{tolerance} cm-1 of {target} cm-1 "
                f"(spectrum covers {x.min():.1f}-{x.max():.1f} cm-1)"
            )
        reference = float(y[window].max())

    if reference == 0:
        raise ValueError(
            "normalize_peak: the reference band has zero intensity — nothing to scale to."
        )
    return x, y / reference
