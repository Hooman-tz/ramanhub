"""Shared spectrum data-access utilities, used by both the processing
pipeline (Module 2) and the newer visualization/search code (Modules 3-4).

This is the ONE place that knows how to go from "a RawFile row" to a
(wavenumbers, intensities) numpy pair, and the ONE place that defines SNR —
per the architecture doc: "define the SNR calculation once, explicitly, and
apply it consistently so it's actually comparable across submissions."

INTEGRATION SEAM (unchanged from the original Module 1 <-> Module 2 note):
Module 1's parsers extract *metadata*, not a persisted numeric array, so
`load_raw_spectrum` below downloads the raw bytes and does a permissive
two-column (wavenumber, intensity) text parse. Not vendor-format-aware (no
binary formats, no unit conversion) — a reasonable v1 default, not a
long-term design.
"""
from __future__ import annotations

import numpy as np

from app.models.raw_file import RawFile
from app.raman_contract import canonicalize_raman_arrays
from app.storage.s3_client import download_bytes


def parse_two_column_raman(raw_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Downloads `raw_file.storage_bucket/storage_key` and parses a
    two-column (wavenumber, intensity) text body, skipping blank/header/
    non-numeric lines. Returns `(wavenumbers, intensities)`, both 1-D float
    arrays of equal length (possibly empty if nothing parsed)."""
    text = raw_bytes.decode("utf-8", errors="ignore")

    wavenumbers: list[float] = []
    intensities: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            wn = float(parts[0])
            intensity = float(parts[1])
        except ValueError:
            continue
        wavenumbers.append(wn)
        intensities.append(intensity)

    return np.asarray(wavenumbers, dtype=float), np.asarray(intensities, dtype=float)


def load_raw_spectrum(raw_file: RawFile) -> tuple[np.ndarray, np.ndarray]:
    """Load a raw object into the canonical Raman array representation."""
    raw_bytes = download_bytes(raw_file.storage_bucket, raw_file.storage_key)
    wavenumbers, intensities = parse_two_column_raman(raw_bytes)
    canonical_x, canonical_y, _flags = canonicalize_raman_arrays(wavenumbers, intensities)
    return canonical_x, canonical_y


def compute_snr(intensities: np.ndarray) -> float | None:
    """Signal-to-noise ratio, defined once here and reused everywhere a
    spectrum's SNR is needed (Module 4 search/filtering, Module 3 display).

    Definition: `(max(intensity) - median(intensity)) / std(diff(intensity))`
    — peak height above the median (a robust baseline proxy) divided by the
    standard deviation of point-to-point differences (a standard, simple
    noise proxy for spectroscopic data that doesn't require picking a
    "flat" region of the spectrum, which varies per sample). Returns None
    for arrays too short to have a meaningful diff, or where the noise
    estimate is exactly zero (would divide by zero — a perfectly flat or
    degenerate array, not a real spectrum).
    """
    if intensities.size < 2:
        return None
    noise = float(np.std(np.diff(intensities)))
    if noise == 0.0:
        return None
    signal = float(np.max(intensities) - np.median(intensities))
    return signal / noise


def lttb_downsample(x: np.ndarray, y: np.ndarray, n_out: int) -> tuple[np.ndarray, np.ndarray]:
    """Largest-Triangle-Three-Buckets downsampling (Sveinn Steinarsson,
    2013) — picks `n_out` points from `(x, y)` that best preserve the
    visual shape of the curve, for sending large/hyperspectral-adjacent
    arrays to the client without shipping every raw point.

    Always keeps the first and last point. No-ops (returns the input
    unchanged) if there's nothing to downsample.
    """
    n = x.shape[0]
    if n_out >= n or n_out <= 2:
        return x, y

    sampled_x = np.empty(n_out, dtype=x.dtype)
    sampled_y = np.empty(n_out, dtype=y.dtype)
    sampled_x[0], sampled_y[0] = x[0], y[0]
    sampled_x[-1], sampled_y[-1] = x[-1], y[-1]

    # Bucket the interior points (everything but the fixed first/last) into
    # n_out - 2 roughly-equal buckets.
    bucket_edges = np.linspace(1, n - 1, n_out - 1).astype(int)
    a = 0  # index of the previously *selected* point
    for i in range(n_out - 2):
        bucket_start, bucket_end = bucket_edges[i], bucket_edges[i + 1]
        if bucket_end <= bucket_start:
            bucket_end = bucket_start + 1

        # Average point of the *next* bucket, used as the triangle's third vertex.
        next_start, next_end = bucket_end, min(bucket_edges[i + 2] if i + 2 < len(bucket_edges) else n, n)
        if next_end <= next_start:
            next_end = min(next_start + 1, n)
        avg_x = float(np.mean(x[next_start:next_end]))
        avg_y = float(np.mean(y[next_start:next_end]))

        bucket_x = x[bucket_start:bucket_end]
        bucket_y = y[bucket_start:bucket_end]
        # Largest triangle area (point a, each candidate, the next bucket's average).
        areas = np.abs(
            (x[a] - avg_x) * (bucket_y - y[a]) - (x[a] - bucket_x) * (avg_y - y[a])
        )
        best = int(np.argmax(areas))
        chosen = bucket_start + best
        sampled_x[i + 1], sampled_y[i + 1] = x[chosen], y[chosen]
        a = chosen

    return sampled_x, sampled_y
