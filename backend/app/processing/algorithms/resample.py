"""Resample the spectrum onto a uniform wavenumber grid by linear
interpolation.

Two reasons this matters on a data-sharing platform specifically. First,
spectra from different instruments land on different grids, so any
comparison across submissions — the library search, any multivariate model
built on the commons — implicitly resamples one onto the other; doing it as
a recorded step makes that choice explicit and replayable instead of hidden
inside whoever's analysis code. Second, several algorithms (derivative
filters, the Whittaker-based baselines) assume evenly spaced points and
quietly distort where that assumption fails.

Linear interpolation is deliberate for v1: it cannot overshoot or introduce
oscillations near sharp Raman bands the way a spline can, and inventing
structure that wasn't measured is a worse failure on a reproducibility
platform than a slightly soft peak apex. Resampling never extrapolates —
the output grid is clipped to the measured range.
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.resample"
VERSION = "1.0.0"
LABEL = "Resample to uniform grid"
CATEGORY = "axis"
DESCRIPTION = (
    "Linearly interpolates onto an evenly spaced wavenumber grid, so spectra from "
    "different instruments share an axis. Changes the array length."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "step_cm1": {
            "type": "number",
            "minimum": 0,
            "title": "Grid spacing (cm-1)",
            "description": "Mutually exclusive with num_points.",
        },
        "num_points": {
            "type": "integer",
            "minimum": 2,
            "title": "Number of points",
            "description": "Mutually exclusive with step_cm1.",
        },
        "min_cm1": {
            "type": "number",
            "title": "Grid start (cm-1)",
            "description": "Defaults to the spectrum's own minimum. Clipped to the measured "
            "range — this step never extrapolates.",
        },
        "max_cm1": {
            "type": "number",
            "title": "Grid end (cm-1)",
            "description": "Defaults to the spectrum's own maximum.",
        },
    },
}


def apply(wavenumbers: np.ndarray, intensities: np.ndarray, **params):
    x = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if x.size != y.size:
        raise ValueError("resample: wavenumber and intensity arrays must match in length")
    if x.size < 2:
        raise ValueError("resample: needs at least 2 points")

    step_cm1 = params.get("step_cm1")
    num_points = params.get("num_points")
    if (step_cm1 is None) == (num_points is None):
        raise ValueError("resample: supply exactly one of step_cm1 or num_points")

    # np.interp requires an ascending x; vendors write either direction.
    order = np.argsort(x)
    x_sorted, y_sorted = x[order], y[order]

    lo = x_sorted[0] if params.get("min_cm1") is None else float(params["min_cm1"])
    hi = x_sorted[-1] if params.get("max_cm1") is None else float(params["max_cm1"])
    lo = max(lo, x_sorted[0])
    hi = min(hi, x_sorted[-1])
    if lo >= hi:
        raise ValueError(
            f"resample: the requested grid does not overlap the measured range "
            f"({x_sorted[0]:.1f}-{x_sorted[-1]:.1f} cm-1)"
        )

    if step_cm1 is not None:
        step = float(step_cm1)
        if step <= 0:
            raise ValueError(f"resample: step_cm1 must be positive, got {step}")
        if step > hi - lo:
            raise ValueError(
                f"resample: step_cm1 ({step}) is wider than the range being resampled "
                f"({hi - lo:.1f} cm-1)"
            )
        grid = np.arange(lo, hi + step / 2, step)
        # arange's float accumulation can overshoot the endpoint by an
        # epsilon; interpolating past hi would silently extrapolate.
        grid = grid[grid <= hi]
    else:
        grid = np.linspace(lo, hi, int(num_points))

    return grid, np.interp(grid, x_sorted, y_sorted)
