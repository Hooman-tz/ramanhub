"""airPLS — Adaptive Iteratively Reweighted Penalized Least Squares baseline
correction, used here for Raman fluorescence-background suppression.

Reference: Zhang, Z.-M., Chen, S., & Liang, Y.-Z. (2010). "Baseline
correction using adaptive iteratively reweighted penalized least squares."
Analyst, 135(5), 1138-1146.

Algorithm sketch: alternate between (1) fitting a smooth baseline to the
spectrum via a weighted, banded second-derivative-penalized least-squares
solve (a Whittaker smoother), and (2) down-weighting points that lie above
the current baseline (weight -> 0, i.e. "this is signal, not background")
while up-weighting points below it (weight grows with how far below, i.e.
"this looks like background"), so the baseline is iteratively pulled toward
the lower envelope of the spectrum. Converges when the residual mass below
the baseline becomes negligible relative to the total signal, or after
`max_iter` iterations.
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve

VERSION = "1.0.0"


def _whittaker_smooth(y: np.ndarray, weights: np.ndarray, lambda_: float, order: int = 2) -> np.ndarray:
    """Weighted penalized least-squares smoother: minimizes
    `sum(w * (y - z)^2) + lambda_ * sum((D^order z)^2)` over `z`, where `D`
    is the discrete-difference operator. This is the per-iteration solve
    that airPLS re-runs with updated `weights`.
    """
    m = y.shape[0]
    eye = sparse.eye(m, format="csc")
    d = eye
    for _ in range(order):
        d = d[1:] - d[:-1]
    w = sparse.diags(weights, 0, shape=(m, m))
    a = (w + lambda_ * (d.T @ d)).tocsc()
    b = weights * y
    return np.asarray(spsolve(a, b))


def _airpls_baseline(
    y: np.ndarray, lambda_: float = 100, max_iter: int = 15, order: int = 2
) -> np.ndarray:
    m = y.shape[0]
    weights = np.ones(m)
    baseline = y.copy()
    total_abs = np.abs(y).sum() or 1.0  # guard against an all-zero spectrum

    for i in range(1, max_iter + 1):
        baseline = _whittaker_smooth(y, weights, lambda_, order)
        residual = y - baseline
        negative_mask = residual < 0
        neg_sum = np.abs(residual[negative_mask]).sum()

        if neg_sum < 1e-3 * total_abs or i == max_iter:
            break

        weights[~negative_mask] = 0
        weights[negative_mask] = np.exp(i * np.abs(residual[negative_mask]) / neg_sum)
        weights[0] = np.exp(i * np.abs(residual).max() / neg_sum)
        weights[-1] = weights[0]

    return baseline


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    """Return the spectrum with the estimated fluorescence/baseline removed
    (`spectrum - baseline`).

    Params: `lambda_` (smoothness penalty, default 100 — larger means a
    stiffer/smoother baseline that resists following sharp peaks) and
    `max_iter` (default 15).
    """
    lambda_ = params.get("lambda_", 100)
    max_iter = params.get("max_iter", 15)
    x = np.asarray(spectrum, dtype=float)
    baseline = _airpls_baseline(x, lambda_=lambda_, max_iter=max_iter)
    return x - baseline
