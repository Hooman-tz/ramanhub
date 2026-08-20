"""Shared expectations for the two new baseline methods.

Both are held to the same contract as the existing airPLS step: after
correction the off-peak regions sit near zero, and the real bands keep their
positions and (approximately) their heights. Parameterizing over both makes
it obvious when one method regresses relative to the other.
"""
import numpy as np
import pytest

from app.processing.algorithms import baseline_als, baseline_polynomial

from ._synthetic import peak_indices, synthetic_spectrum


def _correct(module, wavenumbers, intensities, **params):
    """Call either module through its own convention (AsLS is
    intensity-only, ModPoly is axis-aware) and return intensities."""
    if module is baseline_polynomial:
        _wavenumbers, corrected = module.apply(wavenumbers, intensities, **params)
        return corrected
    return module.apply(intensities, **params)


PARAMS = {
    baseline_als: {"lam": 1e6, "p": 0.01, "max_iter": 20},
    baseline_polynomial: {"degree": 5, "max_iter": 200},
}


@pytest.mark.parametrize("module", [baseline_als, baseline_polynomial])
def test_flattens_off_peak_regions(module):
    wavenumbers, intensities = synthetic_spectrum(with_background=True)

    corrected = _correct(module, wavenumbers, intensities, **PARAMS[module])

    off_peak = np.ones_like(wavenumbers, dtype=bool)
    for index in peak_indices(wavenumbers):
        off_peak[max(0, index - 40) : index + 40] = False

    assert np.abs(corrected[off_peak]).mean() < 0.05 * np.abs(intensities[off_peak]).mean()


@pytest.mark.parametrize("module", [baseline_als, baseline_polynomial])
def test_preserves_peak_positions(module):
    wavenumbers, intensities = synthetic_spectrum(with_background=True)

    corrected = _correct(module, wavenumbers, intensities, **PARAMS[module])

    for index in peak_indices(wavenumbers):
        window = corrected[index - 20 : index + 20]
        assert abs(int(np.argmax(window)) - 20) <= 3


@pytest.mark.parametrize("module", [baseline_als, baseline_polynomial])
def test_does_not_swallow_peak_intensity(module):
    """The failure mode that matters scientifically: a baseline that follows
    the peaks removes real signal along with the background."""
    wavenumbers, intensities = synthetic_spectrum(with_background=True)

    corrected = _correct(module, wavenumbers, intensities, **PARAMS[module])

    for index in peak_indices(wavenumbers):
        assert corrected[index] > 70.0  # true band height is 100


def test_als_rejects_out_of_range_asymmetry():
    _wavenumbers, intensities = synthetic_spectrum(with_background=True)

    with pytest.raises(ValueError, match="p must be"):
        baseline_als.apply(intensities, p=1.5)


def test_polynomial_rejects_degree_at_or_above_spectrum_length():
    short_x = np.linspace(200.0, 300.0, 4)

    with pytest.raises(ValueError, match="degree"):
        baseline_polynomial.apply(short_x, np.ones(4), degree=5)


def test_polynomial_fit_is_stable_against_large_wavenumbers():
    """Degree-5 terms over a raw ~3000 cm-1 axis reach ~1e17 and lose
    conditioning; the implementation rescales the axis to avoid that."""
    wavenumbers, intensities = synthetic_spectrum(with_background=True)

    _wavenumbers, corrected = baseline_polynomial.apply(wavenumbers, intensities, degree=7)

    assert np.isfinite(corrected).all()
