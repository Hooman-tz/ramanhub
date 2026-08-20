"""Min-max normalization: rescale a spectrum onto a fixed interval.

The simplest way to make spectra visually comparable — every spectrum ends
up spanning the same range regardless of acquisition intensity. It is *not*
robust: a single surviving cosmic-ray spike sets the maximum and squashes
everything real down near the floor, so despiking first is not optional.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.normalize.minmax"
VERSION = "1.0.0"
LABEL = "Min-max normalization"
CATEGORY = "normalization"
DESCRIPTION = (
    "Linearly rescales the spectrum so its minimum and maximum land on a fixed interval "
    "(0 to 1 by default). Despike first — one spike will set the maximum."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "lower": {"type": "number", "default": 0.0, "title": "Output minimum"},
        "upper": {"type": "number", "default": 1.0, "title": "Output maximum"},
    },
}


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    lower = float(params.get("lower", 0.0))
    upper = float(params.get("upper", 1.0))
    if upper <= lower:
        raise ValueError(
            f"normalize_minmax: upper ({upper}) must be greater than lower ({lower})"
        )

    x = np.asarray(spectrum, dtype=float)
    span = float(x.max() - x.min())
    if span == 0:
        raise ValueError(
            "normalize_minmax is undefined for a constant (zero-range) spectrum."
        )
    return lower + (x - x.min()) * (upper - lower) / span
