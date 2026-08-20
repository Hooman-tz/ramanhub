"""ModPoly polynomial baseline correction.

Reference: Lieber, C. A., & Mahadevan-Jansen, A. (2003). "Automated method
for subtraction of fluorescence from biological Raman spectra." Applied
Spectroscopy, 57(11), 1363-1367.

A plain polynomial fit to a Raman spectrum sits *through* the peaks rather
than under them, because tall bands drag the least-squares fit upward.
ModPoly fixes this by iterating: fit a polynomial, then clip the working
spectrum down to `min(spectrum, fit)` — anything sticking up above the
current estimate is peak, not background, so it is replaced by the estimate
and stops pulling on the next fit. Repeat until the fit stops moving.

Why keep this alongside the two Whittaker-based baselines: a low-order
polynomial cannot follow narrow structure at all, which is exactly what you
want when the background is genuinely smooth and broad and you want a
strong guarantee that no peak intensity is absorbed into the baseline. It is
also the method most commonly reported in older Raman literature, so
reproducing a published pipeline often requires it specifically.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.baseline.polynomial"
VERSION = "1.0.0"
LABEL = "Baseline correction (ModPoly)"
CATEGORY = "baseline"
DESCRIPTION = (
    "Iterative polynomial baseline subtraction (Lieber & Mahadevan-Jansen ModPoly), where "
    "points above the running fit are clipped so peaks can't drag the baseline upward."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "degree": {
            "type": "integer",
            "default": 5,
            "minimum": 1,
            "title": "Polynomial degree",
            "description": "3 to 7 is typical. Too high starts following peaks.",
        },
        "max_iter": {
            "type": "integer",
            "default": 100,
            "minimum": 1,
            "title": "Max iterations",
        },
        "tol": {
            "type": "number",
            "default": 1e-3,
            "minimum": 0,
            "title": "Convergence tolerance",
            "description": "Stops when the relative change in the fit falls below this.",
        },
    },
}


def compute_baseline(
    wavenumbers: np.ndarray,
    y: np.ndarray,
    degree: int = 5,
    max_iter: int = 100,
    tol: float = 1e-3,
) -> np.ndarray:
    """Return the fitted ModPoly baseline for `y` (not the corrected
    spectrum)."""
    if y.size <= degree:
        raise ValueError(
            f"baseline_polynomial: spectrum length ({y.size}) must exceed degree ({degree})"
        )
    # Fit against a normalized axis rather than raw wavenumbers: a degree-5
    # fit over x ~ 3000 otherwise builds terms around 1e17 and loses
    # conditioning. Rescaling to [-1, 1] is numerically equivalent and stable.
    span = wavenumbers.max() - wavenumbers.min()
    x = (
        2 * (wavenumbers - wavenumbers.min()) / span - 1
        if span > 0
        else np.zeros_like(wavenumbers)
    )

    working = y.copy()
    previous = np.polyval(np.polyfit(x, working, degree), x)
    for _ in range(max_iter):
        working = np.minimum(working, previous)
        current = np.polyval(np.polyfit(x, working, degree), x)
        scale = float(np.abs(previous).sum())
        if scale == 0:
            return current
        if float(np.abs(current - previous).sum()) / scale < tol:
            return current
        previous = current
    return previous


def apply(wavenumbers: np.ndarray, intensities: np.ndarray, **params):
    """Return `(wavenumbers, intensities - baseline)`. Axis-aware because the
    polynomial is fitted against the wavenumber axis — fitting against the
    sample index instead would give a different baseline on any spectrum
    whose points aren't evenly spaced."""
    x = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)
    baseline = compute_baseline(
        x,
        y,
        degree=int(params.get("degree", 5)),
        max_iter=int(params.get("max_iter", 100)),
        tol=float(params.get("tol", 1e-3)),
    )
    return x, y - baseline
