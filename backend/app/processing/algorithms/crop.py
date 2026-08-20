"""Crop the spectrum to a wavenumber range.

Almost every real Raman workflow starts by discarding something: the region
below ~100 cm-1 where the Rayleigh filter cuts in, the detector's noisy
long-wavelength edge, or everything outside the fingerprint region when
that's all the analysis needs. Doing it as an explicit, recorded ledger step
rather than silently in an analysis script is precisely the reproducibility
guarantee this platform exists to provide.

This is one of two steps that changes the wavenumber axis (see
`raman.resample`). Steps ordered after it see the shortened arrays — which
matters for MSC, whose inline reference must match the spectrum's length.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.crop"
VERSION = "1.0.0"
LABEL = "Crop wavenumber range"
CATEGORY = "axis"
DESCRIPTION = (
    "Keeps only the points within a wavenumber range — e.g. dropping the Rayleigh cut-on "
    "region or restricting to the fingerprint region. Changes the array length."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "min_cm1": {
            "type": "number",
            "title": "Minimum (cm-1)",
            "description": "Leave empty for no lower bound.",
        },
        "max_cm1": {
            "type": "number",
            "title": "Maximum (cm-1)",
            "description": "Leave empty for no upper bound.",
        },
    },
}


def apply(wavenumbers: np.ndarray, intensities: np.ndarray, **params):
    x = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if x.size != y.size:
        raise ValueError("crop: wavenumber and intensity arrays must match in length")

    min_cm1 = params.get("min_cm1")
    max_cm1 = params.get("max_cm1")
    if min_cm1 is None and max_cm1 is None:
        raise ValueError("crop: at least one of min_cm1 / max_cm1 is required")
    if min_cm1 is not None and max_cm1 is not None and float(min_cm1) >= float(max_cm1):
        raise ValueError(
            f"crop: min_cm1 ({min_cm1}) must be less than max_cm1 ({max_cm1})"
        )

    mask = np.ones(x.size, dtype=bool)
    if min_cm1 is not None:
        mask &= x >= float(min_cm1)
    if max_cm1 is not None:
        mask &= x <= float(max_cm1)
    if not mask.any():
        raise ValueError(
            f"crop: no points fall in the requested range (spectrum covers "
            f"{x.min():.1f}-{x.max():.1f} cm-1)"
        )
    return x[mask], y[mask]
