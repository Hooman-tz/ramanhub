"""Overlay math for a Finding's member spectra: a mean curve plus a
per-point standard-deviation band, computed live from spectrum data.

Deliberately NOT under `app/processing/` — that package stays a separable
signal-processing unit. This is presentation-layer aggregation that *reuses*
the analysis grid helper (`_shared_grid`) and the LTTB downsampler rather
than adding anything to the toolbox.
"""
from __future__ import annotations

import numpy as np

from app.analysis.engine import _shared_grid
from app.spectra_io import lttb_downsample


def _single(x: np.ndarray, y: np.ndarray, grid_points: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    grid = np.linspace(float(x[0]), float(x[-1]), grid_points)
    mean = np.interp(grid, x, y)
    return grid, mean, np.zeros_like(mean)


def _downsample_triplet(
    grid: np.ndarray, mean: np.ndarray, std: np.ndarray, max_points: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Downsample `grid` with LTTB (shape-preserving) then re-interpolate
    `mean`/`std` onto the reduced grid so all three arrays stay aligned."""
    if grid.shape[0] <= max_points:
        return grid, mean, std
    reduced_grid, _reduced_mean = lttb_downsample(grid, mean, max_points)
    return (
        reduced_grid,
        np.interp(reduced_grid, grid, mean),
        np.interp(reduced_grid, grid, std),
    )


def compute_overlay(
    arrays: list[tuple[np.ndarray, np.ndarray]],
    *,
    grid_points: int,
    max_points: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return aligned `(grid_wavenumbers, mean, std)` 1-D float arrays.

    - 0 arrays  -> three empty arrays.
    - 1 array   -> that spectrum resampled onto a `grid_points` linspace over
      its own range as `mean`; `std` all zeros.
    - >=2 arrays -> `_shared_grid` (needs >=80% wavenumber overlap); on
      insufficient overlap, fall back to the intersection range
      `[max(x[0]), min(x[-1])]` and `np.interp` each spectrum onto a
      `grid_points` linspace there; if that intersection is empty, behave
      like the 1-array case using the first array.

    `mean`/`std` are the column mean / population std of the resampled
    matrix. The result is finally LTTB-downsampled to `max_points`.
    """
    if not arrays:
        empty = np.asarray([], dtype=float)
        return empty, empty.copy(), empty.copy()

    if len(arrays) == 1:
        x, y = arrays[0]
        return _downsample_triplet(*_single(x, y, grid_points), max_points)

    try:
        grid, matrix = _shared_grid(arrays, grid_points)
    except ValueError:
        left = max(float(x[0]) for x, _y in arrays)
        right = min(float(x[-1]) for x, _y in arrays)
        if right <= left:
            x, y = arrays[0]
            return _downsample_triplet(*_single(x, y, grid_points), max_points)
        grid = np.linspace(left, right, grid_points)
        matrix = np.vstack([np.interp(grid, x, y) for x, y in arrays])

    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    return _downsample_triplet(grid, mean, std, max_points)
