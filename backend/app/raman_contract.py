"""Raman-specific validation shared by ingestion, storage, and publication.

This module deliberately keeps the scientific contract explicit rather than
letting each route invent its own interpretation of a "valid" Raman upload.
"""
from __future__ import annotations

import hashlib

import numpy as np

RAMAN_CANONICALIZATION_VERSION = "raman-1"
WAVENUMBER_UNIT = "cm-1"
INTENSITY_UNIT = "a.u."
MIN_CANONICAL_POINTS = 2


class RamanDataError(ValueError):
    """Raised when an array cannot satisfy the canonical Raman representation."""


def canonicalize_raman_arrays(
    wavenumbers: np.ndarray, intensities: np.ndarray
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Return finite, ascending, duplicate-free 1-D Raman arrays.

    The raw object is never changed. This only defines the representation used
    by visualization, processing, and quality checks. Duplicate wavenumbers
    are averaged deterministically; other repairs are reported as QC flags.
    """
    x = np.asarray(wavenumbers, dtype=float).reshape(-1)
    y = np.asarray(intensities, dtype=float).reshape(-1)
    if x.size != y.size:
        raise RamanDataError("wavenumber and intensity arrays have different lengths")

    finite = np.isfinite(x) & np.isfinite(y)
    flags: list[str] = []
    if not np.all(finite):
        x, y = x[finite], y[finite]
        flags.append("non_finite_points_removed")
    if x.size < MIN_CANONICAL_POINTS:
        raise RamanDataError(f"at least {MIN_CANONICAL_POINTS} finite points are required")

    if np.any(np.diff(x) < 0):
        order = np.argsort(x, kind="stable")
        x, y = x[order], y[order]
        flags.append("wavenumbers_sorted_ascending")

    unique_x, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    if unique_x.size != x.size:
        sums = np.zeros(unique_x.size, dtype=float)
        np.add.at(sums, inverse, y)
        x, y = unique_x, sums / counts
        flags.append("duplicate_wavenumbers_averaged")

    if x.size < MIN_CANONICAL_POINTS or np.any(np.diff(x) <= 0):
        raise RamanDataError("wavenumbers must be strictly ascending after canonicalization")
    return x, y, flags


def checksum_bytes(data: bytes) -> str:
    """Return the SHA-256 checksum format stored with immutable raw objects."""
    return hashlib.sha256(data).hexdigest()