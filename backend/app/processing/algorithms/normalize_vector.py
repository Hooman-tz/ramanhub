"""Vector (L2 / unit-norm) normalization.

Divides the spectrum by its Euclidean norm, so every spectrum becomes a unit
vector. This is the normalization that pairs naturally with the platform's
cosine-similarity library search (`/search/similar/{id}`), which is itself
defined on unit-normalized vectors — normalizing here makes the geometry the
search operates on explicit in the ledger rather than implicit in the
scoring function.

Unlike SNV it does not center the spectrum, so an additive background
survives it: subtract a baseline first if the data has one.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.normalize.vector"
VERSION = "1.0.0"
LABEL = "Vector (unit-norm) normalization"
CATEGORY = "normalization"
DESCRIPTION = (
    "Divides the spectrum by its Euclidean (L2) norm, giving unit length — the same "
    "geometry cosine-similarity library search uses."
)
PARAM_SCHEMA = {"type": "object", "properties": {}}


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    x = np.asarray(spectrum, dtype=float)
    norm = float(np.linalg.norm(x))
    if norm == 0:
        raise ValueError(
            "normalize_vector is undefined for an all-zero spectrum (zero norm)."
        )
    return x / norm
