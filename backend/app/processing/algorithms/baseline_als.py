"""Asymmetric Least Squares (AsLS) baseline correction.

Reference: Eilers, P. H. C., & Boelens, H. F. M. (2005). "Baseline
correction with asymmetric least squares smoothing." Leiden University
Medical Centre report.

Fits a Whittaker smoother to the spectrum under an asymmetric weighting:
points above the current baseline get weight `p` (small, e.g. 0.01 — "this
is probably a peak, ignore it") and points below get weight `1 - p` ("this
is probably background, follow it"). Iterating pulls the baseline down onto
the lower envelope.

Relationship to the sibling `raman.fluorescence_suppression.airpls` step:
both are Whittaker-smoother baselines, differing only in how weights are
updated. AsLS uses a fixed asymmetry `p`; airPLS recomputes weights each
iteration from the size of the residual, which adapts better to a strongly
curved fluorescence background. AsLS is kept as a separate step because it
is the more predictable, better-known of the two, and its two parameters map
directly onto what practitioners already tune elsewhere.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

STEP_TYPE = "raman.baseline.als"
VERSION = "1.0.0"
LABEL = "Baseline correction (asymmetric least squares)"
CATEGORY = "baseline"
DESCRIPTION = (
    "Eilers & Boelens AsLS baseline subtraction — a smooth baseline fitted with peaks "
    "down-weighted by a fixed asymmetry factor."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "lam": {
            "type": "number",
            "default": 1e5,
            "minimum": 0,
            "title": "Smoothness (lambda)",
            "description": "Typically 1e2 to 1e9. Larger means a stiffer baseline.",
        },
        "p": {
            "type": "number",
            "default": 0.01,
            "minimum": 0,
            "maximum": 1,
            "title": "Asymmetry (p)",
            "description": "Weight given to points above the baseline. Typically 0.001 to 0.1.",
        },
        "max_iter": {
            "type": "integer",
            "default": 10,
            "minimum": 1,
            "title": "Max iterations",
        },
    },
}


def compute_baseline(
    y: np.ndarray, lam: float = 1e5, p: float = 0.01, max_iter: int = 10
) -> np.ndarray:
    """Return the fitted AsLS baseline for `y` (not the corrected spectrum)."""
    if not 0 <= p <= 1:
        raise ValueError(f"baseline_als: p must be between 0 and 1, got {p}")
    m = y.shape[0]
    if m < 3:
        raise ValueError("baseline_als: needs at least 3 points")

    # Second-difference operator, as a sparse matrix so the per-iteration
    # solve stays banded and cheap even for long spectra.
    d = sparse.eye(m, format="csc")
    d = d[1:] - d[:-1]
    d = d[1:] - d[:-1]
    penalty = lam * (d.T @ d)

    weights = np.ones(m)
    baseline = y.copy()
    for _ in range(max_iter):
        w = sparse.diags(weights, 0, shape=(m, m))
        baseline = np.asarray(spsolve((w + penalty).tocsc(), weights * y))
        weights = np.where(y > baseline, p, 1.0 - p)
    return baseline


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    """Return `spectrum - baseline`."""
    x = np.asarray(spectrum, dtype=float)
    baseline = compute_baseline(
        x,
        lam=float(params.get("lam", 1e5)),
        p=float(params.get("p", 0.01)),
        max_iter=int(params.get("max_iter", 10)),
    )
    return x - baseline
