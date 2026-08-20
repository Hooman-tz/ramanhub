"""Shared synthetic-spectrum builders for the preprocessing-suite tests.

Every algorithm here is judged against the same question — "does it remove
the artifact it targets without damaging the real Raman bands?" — so the
tests share one spectrum generator with individually switchable artifacts
(fluorescence background, cosmic-ray spikes, noise) rather than each test
module rolling its own.
"""
from __future__ import annotations

import numpy as np

PEAK_CENTERS_CM1 = (620.0, 1050.0, 1600.0)


def gaussian(x: np.ndarray, center: float, amplitude: float, width: float) -> np.ndarray:
    return amplitude * np.exp(-((x - center) ** 2) / (2 * width**2))


def synthetic_spectrum(
    *,
    n_points: int = 1000,
    with_background: bool = False,
    spike_indices: tuple[int, ...] = (),
    spike_amplitude: float = 500.0,
    noise_sigma: float = 0.0,
    seed: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Return `(wavenumbers, intensities)` over a realistic 200-3200 cm-1
    Raman range with three Gaussian bands, plus whichever artifacts the
    caller asks for."""
    wavenumbers = np.linspace(200.0, 3200.0, n_points)
    intensities = np.zeros_like(wavenumbers)
    for center in PEAK_CENTERS_CM1:
        intensities += gaussian(wavenumbers, center, amplitude=100.0, width=15.0)

    if with_background:
        # Broad, smoothly rising fluorescence — the dominant real-world
        # artifact, and much larger than the bands sitting on it.
        normalized = (wavenumbers - wavenumbers.min()) / np.ptp(wavenumbers)
        intensities += 400.0 * np.exp(-3.0 * normalized) + 50.0

    if noise_sigma:
        intensities += np.random.default_rng(seed).normal(0, noise_sigma, size=intensities.shape)

    for index in spike_indices:
        intensities[index] += spike_amplitude

    return wavenumbers, intensities


def peak_indices(wavenumbers: np.ndarray) -> list[int]:
    return [int(np.argmin(np.abs(wavenumbers - center))) for center in PEAK_CENTERS_CM1]
