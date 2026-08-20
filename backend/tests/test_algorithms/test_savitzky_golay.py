import numpy as np
import pytest

from app.processing.algorithms import savitzky_golay as sg

from ._synthetic import peak_indices, synthetic_spectrum


def test_reduces_noise():
    _wavenumbers, clean = synthetic_spectrum()
    _wavenumbers, noisy = synthetic_spectrum(noise_sigma=3.0)

    smoothed = sg.apply(noisy, window_length=11, polyorder=3)

    assert np.abs(smoothed - clean).std() < np.abs(noisy - clean).std()


def test_preserves_peak_height_far_better_than_a_moving_average():
    """The reason Savitzky-Golay is the spectroscopy default: an equal-width
    boxcar visibly flattens sharp bands, SG does not."""
    wavenumbers, intensities = synthetic_spectrum()
    window = 11

    smoothed = sg.apply(intensities, window_length=window, polyorder=3)
    boxcar = np.convolve(intensities, np.ones(window) / window, mode="same")

    for index in peak_indices(wavenumbers):
        true_height = intensities[index]
        assert abs(smoothed[index] - true_height) < abs(boxcar[index] - true_height)
        assert smoothed[index] == pytest.approx(true_height, rel=0.02)


def test_first_derivative_crosses_zero_at_peak_centres():
    wavenumbers, intensities = synthetic_spectrum()

    derivative = sg.apply(intensities, window_length=11, polyorder=3, deriv=1)

    for index in peak_indices(wavenumbers):
        assert derivative[index - 5] > 0  # rising into the peak
        assert derivative[index + 5] < 0  # falling out of it


def test_rejects_even_window_length():
    _wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="odd"):
        sg.apply(intensities, window_length=10, polyorder=3)


def test_rejects_polyorder_not_less_than_window():
    _wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="polyorder"):
        sg.apply(intensities, window_length=5, polyorder=5)


def test_rejects_window_longer_than_spectrum():
    with pytest.raises(ValueError, match="exceeds"):
        sg.apply(np.arange(7, dtype=float), window_length=9, polyorder=3)
