"""Standard Normal Variate (SNV) normalization.

SNV row-centers and scales a spectrum to zero mean / unit variance:
`(x - mean(x)) / std(x)`. It is a per-spectrum operation with no external
reference, so its only knob is the optional `ddof`, forwarded to
`numpy.std`.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.snv"
VERSION = "1.0.0"
LABEL = "SNV normalization"
CATEGORY = "normalization"
DESCRIPTION = "Standard Normal Variate normalization: centers to zero mean and scales to unit variance."
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "ddof": {
            "type": "integer",
            "default": 0,
            "title": "Delta degrees of freedom",
            "description": "Forwarded to numpy.std; 0 for the population standard deviation.",
        }
    },
}


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    """Return the SNV-normalized spectrum.

    Raises `ValueError` if the input has zero standard deviation (a
    perfectly flat/constant spectrum) — normalizing would divide by zero.
    We deliberately raise rather than silently returning zeros, since a flat
    "spectrum" is almost always bad/placeholder input worth surfacing to the
    caller rather than masking.
    """
    x = np.asarray(spectrum, dtype=float)
    ddof = params.get("ddof", 0)
    std = x.std(ddof=ddof)
    if std == 0:
        raise ValueError(
            "SNV is undefined for a constant (zero standard deviation) spectrum."
        )
    return (x - x.mean()) / std
