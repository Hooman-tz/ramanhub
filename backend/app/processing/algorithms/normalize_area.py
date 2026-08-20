"""Area normalization: divide by the integrated area under the spectrum.

Axis-aware, and that's the point — the integral is taken over the wavenumber
axis by the trapezoidal rule, not over the sample index. On an unevenly
sampled spectrum (common after stitching acquisition windows, and after this
platform's own `raman.crop`) those two give different answers, and only the
former is physically meaningful.

Area normalization is the right choice when total scattered intensity is the
nuisance variable — e.g. comparing the same material measured at different
laser powers or integration times — because it preserves the *relative* band
shape exactly while removing the overall scale.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.normalize.area"
VERSION = "1.0.0"
LABEL = "Area normalization"
CATEGORY = "normalization"
DESCRIPTION = (
    "Divides by the integrated area under the curve (trapezoidal, over the wavenumber "
    "axis) so every spectrum has unit area. Removes overall intensity scale while "
    "preserving relative band shape."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "use_absolute": {
            "type": "boolean",
            "default": True,
            "title": "Integrate absolute values",
            "description": "Recommended after baseline correction, where residual negative "
            "regions would otherwise cancel positive signal and shrink the area.",
        }
    },
}


def apply(wavenumbers: np.ndarray, intensities: np.ndarray, **params):
    use_absolute = bool(params.get("use_absolute", True))
    x = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if x.size != y.size:
        raise ValueError("normalize_area: wavenumber and intensity arrays must match in length")
    if x.size < 2:
        raise ValueError("normalize_area: needs at least 2 points to integrate")

    # Integrate along an ascending axis: some vendors write wavenumbers
    # descending, and trapezoidal integration over a descending x returns a
    # negative area, which would flip the whole spectrum's sign here.
    order = np.argsort(x)
    integrand = np.abs(y) if use_absolute else y
    area = float(np.trapezoid(integrand[order], x[order]))
    if area == 0:
        raise ValueError(
            "normalize_area is undefined for a spectrum with zero integrated area."
        )
    return x, y / area
