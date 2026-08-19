"""Standard Normal Variate (SNV) normalization.

SNV row-centers and scales a spectrum to zero mean / unit variance:
`(x - mean(x)) / std(x)`. It is a per-spectrum operation with no external
reference, so its param schema is empty (`{}` in the seeded
`LedgerStepDefinition` row) — the only accepted (optional) knob is `ddof`,
forwarded to `numpy.std`.
"""
from __future__ import annotations

import numpy as np

VERSION = "1.0.0"


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
