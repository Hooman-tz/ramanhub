"""Peak detection tests.

The bar throughout: the synthetic spectrum in `tests/test_algorithms/
_synthetic.py` has three Gaussian bands at KNOWN centres, so "did it work"
is a question with a right answer in cm-1 — not "did it return something".
"""
from __future__ import annotations

import numpy as np
import pytest

from app.analysis.peaks import detect_peaks
from tests.test_algorithms._synthetic import PEAK_CENTERS_CM1, synthetic_spectrum


def _centers(peaks) -> list[float]:
    return [p.wavenumber for p in peaks]


def test_finds_the_three_known_bands():
    x, y = synthetic_spectrum()
    peaks = detect_peaks(x, y)

    assert len(peaks) == 3
    for found, expected in zip(_centers(peaks), PEAK_CENTERS_CM1, strict=True):
        # The grid is ~3 cm-1/point over 200-3200, so the apex can only land
        # within a sample of the true centre.
        assert abs(found - expected) < 5.0


def test_results_are_sorted_by_wavenumber():
    x, y = synthetic_spectrum()
    centers = _centers(detect_peaks(x, y))
    assert centers == sorted(centers)


def test_fwhm_recovers_the_gaussian_width():
    """The generator uses width=15.0 as the Gaussian sigma, so the true
    FWHM is 2*sqrt(2 ln2)*sigma ~= 35.3 cm-1. If this drifts, the
    sample-to-cm-1 conversion has broken."""
    x, y = synthetic_spectrum()
    peaks = detect_peaks(x, y)
    expected_fwhm = 2.0 * np.sqrt(2.0 * np.log(2.0)) * 15.0

    for peak in peaks:
        assert peak.fwhm_cm1 is not None
        assert abs(peak.fwhm_cm1 - expected_fwhm) < 3.0


def test_descending_axis_gives_the_same_peaks():
    """Vendors write the wavenumber axis in either direction; a spectrum
    stored high-to-low must not report different bands."""
    x, y = synthetic_spectrum()
    ascending = _centers(detect_peaks(x, y))
    descending = _centers(detect_peaks(x[::-1], y[::-1]))

    assert descending == pytest.approx(ascending)


def test_prominence_is_scale_independent():
    """The whole reason prominence is expressed as a fraction of range:
    multiplying a spectrum by 1000 (counts vs. counts/second) must not
    change which peaks are found."""
    x, y = synthetic_spectrum()
    assert _centers(detect_peaks(x, y)) == pytest.approx(_centers(detect_peaks(x, y * 1000.0)))


def test_higher_prominence_finds_fewer_peaks():
    """Exercises the prominence knob with the noise floor switched off —
    with it on, it correctly dominates at low fractions and both settings
    return the same three bands (see the noise-floor tests below)."""
    x, y = synthetic_spectrum(noise_sigma=2.0)
    sensitive = detect_peaks(x, y, prominence_fraction=0.001, noise_multiple=0)
    strict = detect_peaks(x, y, prominence_fraction=0.3, noise_multiple=0)

    assert len(sensitive) > len(strict)


def test_noise_peaks_are_rejected_at_the_default_threshold():
    """Noise must not be reported as bands — the default has to be usable
    as a one-click action on a real, noisy spectrum."""
    x, y = synthetic_spectrum(noise_sigma=3.0)
    peaks = detect_peaks(x, y)

    assert len(peaks) == 3


def test_noise_floor_is_what_rejects_them():
    """Guards the fix directly: without the noise floor the same spectrum
    floods with false peaks, so this asserts the floor is load-bearing and
    not incidentally masked by the fraction-of-range term."""
    x, y = synthetic_spectrum(noise_sigma=3.0)

    assert len(detect_peaks(x, y, noise_multiple=0)) > 10
    assert len(detect_peaks(x, y)) == 3


def test_noise_estimate_is_not_inflated_by_real_bands():
    """The reason MAD replaced std(diff): a clean spectrum's own peak
    flanks must not read as noise, or the detector rejects its own bands."""
    from app.analysis.peaks import estimate_noise_sigma

    _x, clean = synthetic_spectrum()
    _x, noisy = synthetic_spectrum(noise_sigma=3.0)

    assert estimate_noise_sigma(clean) < 1.0
    assert 2.0 < estimate_noise_sigma(noisy) < 4.5


def test_max_peaks_keeps_the_most_prominent():
    x, y = synthetic_spectrum(noise_sigma=2.0)
    limited = detect_peaks(x, y, prominence_fraction=0.001, max_peaks=3)

    assert len(limited) == 3
    # The three real bands dwarf every noise wiggle, so they're what
    # survives the by-prominence truncation.
    for found, expected in zip(_centers(limited), PEAK_CENTERS_CM1, strict=True):
        assert abs(found - expected) < 5.0


def test_min_distance_merges_close_peaks():
    x, y = synthetic_spectrum()
    # 1050 and 1600 are 550 apart; a 1000 cm-1 exclusion window can't keep
    # both.
    peaks = detect_peaks(x, y, min_distance_cm1=1000.0)
    assert len(peaks) < 3


def test_flat_spectrum_returns_no_peaks():
    x = np.linspace(200.0, 3200.0, 500)
    assert detect_peaks(x, np.zeros_like(x)) == []


def test_too_short_returns_no_peaks():
    assert detect_peaks(np.array([1.0, 2.0]), np.array([1.0, 2.0])) == []


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError, match="match in length"):
        detect_peaks(np.arange(10.0), np.arange(5.0))


def test_area_is_positive_for_real_bands():
    x, y = synthetic_spectrum()
    assert all(p.area > 0 for p in detect_peaks(x, y))
