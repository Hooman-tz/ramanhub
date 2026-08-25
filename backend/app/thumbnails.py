"""Server-rendered spectrum sparklines.

## Why SVG on the server rather than a chart in the browser

A profile or a collection grid shows tens of spectra at once. Letting each
tile fetch `/spectra/{id}/data` and mount an ECharts instance means N requests
and N chart instances for what is visually a 200-pixel squiggle. An SVG path
is a few hundred bytes, needs no JavaScript, and the browser caches it.

## Why the x-domain is fixed rather than per-spectrum

This is the part that actually makes a grid of spectra usable, and it is the
real lesson of Instagram's square crop: the mechanic is *uniformity of frame*,
not the grid itself. If every tile auto-scales to its own range, peak
positions land in different pixel columns on every tile and the eye has to
re-read an invisible axis per thumbnail. Pinning all tiles to the same
wavenumber window means a band at 1002 cm-1 is at the same x on every tile, so
shapes become comparable at a glance.

## Why peak ticks

At thumbnail scale a baseline-corrected Raman spectrum is a wiggly line, and
every wiggly line looks like every other wiggly line — a spectral corpus is
maximally visually SIMILAR, which is exactly the case a photo grid is not
designed for. A row of tick marks at detected peak positions reads as a
barcode, and barcodes are discriminable at 200 px where curves are not.

## Caching

No new cache table. The processed arrays are already content-addressed by
ledger hash (`app.processing.cache`), so the expensive half is cached
already; rendering the path from them is microseconds. What this module adds
is an ETag derived from the spectrum id plus its current ledger id, so a
reprocess changes the tag and everything else is a browser 304.
"""
from __future__ import annotations

import numpy as np

# The shared frame. Covers the Raman fingerprint plus the C-H stretch region,
# which is where essentially all reported bands sit.
DEFAULT_RANGE_CM1 = (200.0, 3200.0)

WIDTH = 240
HEIGHT = 72
# Room at the bottom for the peak-tick barcode.
TICK_BAND = 10
PLOT_HEIGHT = HEIGHT - TICK_BAND

# Enough points to preserve band shape at this width, few enough to keep the
# path short. Two samples per pixel column is the useful ceiling.
TARGET_POINTS = WIDTH * 2


def _resample_to_frame(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    x_min: float,
    x_max: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Put the trace on the shared frame.

    Regions the spectrum does not cover are left as NaN rather than
    extrapolated — inventing signal outside the measured range is exactly the
    thing `analysis.common_grid` refuses to do for real analysis, and a
    thumbnail should not quietly do it either. NaNs become gaps in the path.
    """
    order = np.argsort(wavenumbers)
    x, y = np.asarray(wavenumbers, float)[order], np.asarray(intensities, float)[order]

    grid = np.linspace(x_min, x_max, TARGET_POINTS)
    values = np.interp(grid, x, y, left=np.nan, right=np.nan)
    return grid, values


def _normalize(values: np.ndarray) -> np.ndarray:
    """Min-max to 0..1 over the finite samples only.

    Per-tile normalization is correct here even though the x-axis is shared:
    absolute Raman intensity is not comparable between acquisitions anyway
    (counts vs counts/second vs post-SNV), so a shared y-scale would make most
    tiles flat lines. Shape is the comparable thing, and shape is what this
    preserves.
    """
    finite = np.isfinite(values)
    if not finite.any():
        return values
    lo = float(np.nanmin(values))
    hi = float(np.nanmax(values))
    if hi - lo <= 0:
        out = np.full_like(values, 0.5)
        out[~finite] = np.nan
        return out
    return (values - lo) / (hi - lo)


def _path(grid: np.ndarray, values: np.ndarray) -> str:
    """Build the SVG path, breaking it into subpaths across NaN gaps."""
    n = len(grid)
    if n == 0:
        return ""
    xs = np.linspace(0.0, float(WIDTH), n)
    # SVG y grows downward, so a high intensity must map to a small y.
    ys = (1.0 - values) * (PLOT_HEIGHT - 2) + 1

    parts: list[str] = []
    pen_down = False
    for i in range(n):
        if not np.isfinite(ys[i]):
            pen_down = False
            continue
        cmd = "L" if pen_down else "M"
        parts.append(f"{cmd}{xs[i]:.1f} {ys[i]:.1f}")
        pen_down = True
    return "".join(parts)


def _ticks(peak_wavenumbers: list[float], x_min: float, x_max: float) -> str:
    span = x_max - x_min
    if span <= 0:
        return ""
    marks = []
    for wn in peak_wavenumbers:
        if not (x_min <= wn <= x_max):
            continue
        x = (wn - x_min) / span * WIDTH
        marks.append(
            f'<line x1="{x:.1f}" y1="{PLOT_HEIGHT + 2}" x2="{x:.1f}" y2="{HEIGHT - 1}" />'
        )
    return "".join(marks)


def render_sparkline(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    peak_wavenumbers: list[float] | None = None,
    x_range: tuple[float, float] = DEFAULT_RANGE_CM1,
) -> str:
    """Return a standalone SVG string.

    `currentColor` is used throughout so the tile inherits its container's
    colour — that is what lets dark mode work without rendering a second
    variant, and what lets a material-class hue be applied by CSS rather than
    baked into the cached image.
    """
    x_min, x_max = x_range
    grid, values = _resample_to_frame(wavenumbers, intensities, x_min, x_max)
    path = _path(grid, _normalize(values))
    ticks = _ticks(peak_wavenumbers or [], x_min, x_max)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" height="{HEIGHT}" role="img" '
        f'aria-label="Spectrum preview, {x_min:.0f} to {x_max:.0f} reciprocal centimetres">'
        f'<g fill="none" stroke="currentColor" stroke-width="1.2" '
        f'stroke-linejoin="round" stroke-linecap="round">'
        f'<path d="{path}"/></g>'
        f'<g stroke="currentColor" stroke-width="1.5" opacity="0.55">{ticks}</g>'
        f"</svg>"
    )
