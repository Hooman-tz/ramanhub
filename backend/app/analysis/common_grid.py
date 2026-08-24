"""Put N spectra on one wavenumber axis so they can be stacked into a matrix.

Every multivariate method here (PCA, HCA) and every overlay figure needs
this, and it is the step most often done silently and wrongly. Spectra from
different instruments — or even the same instrument at different grating
positions — land on different grids, so column *i* of two spectra is not the
same Raman shift until you make it so.

Two rules, both deliberate:

- The common range is the **intersection** of the inputs' ranges, never the
  union. A union would require extrapolating spectra past where they were
  actually measured, inventing structure that was never recorded — the worst
  possible failure on a reproducibility platform.
- The grid resolution is the **finest input's** resolution, capped, so the
  best-resolved spectrum isn't degraded to match the worst.

This reuses `app.processing.algorithms.resample.apply`, so cross-spectrum
alignment uses exactly the same interpolation as the user-facing `Resample`
ledger step — one behaviour, not two.
"""
from __future__ import annotations

import numpy as np

from app.processing.algorithms import resample

# Upper bound on the common grid's length. Guards the O(n_spectra x n_points)
# matrix that PCA/HCA build from getting large enough to matter for a
# synchronous request; well above any real Raman spectrum's point count.
MAX_GRID_POINTS = 4096


class IncompatibleSpectraError(ValueError):
    """Raised when the inputs share no common wavenumber range, so no
    honest comparison is possible without extrapolating."""


def build_common_grid(
    spectra: list[tuple[np.ndarray, np.ndarray]],
    num_points: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Resample every `(wavenumbers, intensities)` pair onto one shared
    axis.

    Returns `(grid, matrix)` where `grid` is 1-D of length P and `matrix` is
    (N, P) — one row per input spectrum, in the order given.

    Raises `IncompatibleSpectraError` if fewer than two usable spectra
    remain or their ranges don't overlap.
    """
    usable = [(np.asarray(x, float), np.asarray(y, float)) for x, y in spectra]
    usable = [(x, y) for x, y in usable if x.size >= 2 and x.size == y.size]
    if len(usable) < 2:
        raise IncompatibleSpectraError(
            "Need at least 2 spectra with 2+ points each to compare."
        )

    lo = max(float(np.min(x)) for x, _ in usable)
    hi = min(float(np.max(x)) for x, _ in usable)
    if lo >= hi:
        raise IncompatibleSpectraError(
            f"These spectra share no overlapping wavenumber range "
            f"(the common window would be {lo:.1f}-{hi:.1f} cm-1). They were most likely "
            f"measured over different regions and can't be compared point-by-point."
        )

    if num_points is None:
        # Finest input resolution, measured only over the shared window so a
        # spectrum with a long sparse tail doesn't skew the estimate.
        finest = 0
        for x, _ in usable:
            in_window = int(np.sum((x >= lo) & (x <= hi)))
            finest = max(finest, in_window)
        num_points = finest
    num_points = int(np.clip(num_points, 2, MAX_GRID_POINTS))

    grid = np.linspace(lo, hi, num_points)
    rows = []
    for x, y in usable:
        _, resampled = resample.apply(
            x, y, num_points=num_points, min_cm1=lo, max_cm1=hi
        )
        rows.append(resampled)

    return grid, np.vstack(rows)
