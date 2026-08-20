"""Tests for the two steps that change the wavenumber axis itself."""
import numpy as np
import pytest

from app.processing.algorithms import crop, resample

from ._synthetic import PEAK_CENTERS_CM1, synthetic_spectrum

# ---------------------------------------------------------------------------
# Crop
# ---------------------------------------------------------------------------


def test_crop_keeps_only_the_requested_range():
    wavenumbers, intensities = synthetic_spectrum()

    x, y = crop.apply(wavenumbers, intensities, min_cm1=600.0, max_cm1=1700.0)

    assert x.min() >= 600.0
    assert x.max() <= 1700.0
    assert x.size == y.size
    assert x.size < wavenumbers.size


def test_crop_keeps_intensities_aligned_with_their_wavenumbers():
    wavenumbers, intensities = synthetic_spectrum()

    x, y = crop.apply(wavenumbers, intensities, min_cm1=600.0)

    original = {float(w): float(i) for w, i in zip(wavenumbers, intensities, strict=True)}
    for w, i in zip(x, y, strict=True):
        assert original[float(w)] == pytest.approx(float(i))


def test_crop_accepts_a_single_bound():
    wavenumbers, intensities = synthetic_spectrum()

    x, _y = crop.apply(wavenumbers, intensities, max_cm1=1000.0)

    assert x.max() <= 1000.0
    assert x.min() == pytest.approx(wavenumbers.min())


def test_crop_requires_at_least_one_bound():
    wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="at least one"):
        crop.apply(wavenumbers, intensities)


def test_crop_rejects_an_empty_result():
    wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="no points"):
        crop.apply(wavenumbers, intensities, min_cm1=9000.0, max_cm1=9500.0)


def test_crop_rejects_inverted_bounds():
    wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="less than"):
        crop.apply(wavenumbers, intensities, min_cm1=1000.0, max_cm1=500.0)


# ---------------------------------------------------------------------------
# Resample
# ---------------------------------------------------------------------------


def test_resample_to_a_fixed_point_count():
    wavenumbers, intensities = synthetic_spectrum()

    x, y = resample.apply(wavenumbers, intensities, num_points=256)

    assert x.size == 256
    assert y.size == 256
    assert np.allclose(np.diff(x), np.diff(x)[0])  # uniform grid


def test_resample_to_a_fixed_step_produces_that_spacing():
    wavenumbers, intensities = synthetic_spectrum()

    x, _y = resample.apply(wavenumbers, intensities, step_cm1=5.0)

    assert np.allclose(np.diff(x), 5.0)


def test_resample_never_extrapolates_beyond_the_measured_range():
    wavenumbers, intensities = synthetic_spectrum()

    x, _y = resample.apply(
        wavenumbers, intensities, step_cm1=10.0, min_cm1=0.0, max_cm1=9000.0
    )

    assert x.min() >= wavenumbers.min()
    assert x.max() <= wavenumbers.max()


def test_resample_preserves_band_shape():
    """Interpolating onto a denser grid must not move or shrink a peak."""
    wavenumbers, intensities = synthetic_spectrum(n_points=1000)

    x, y = resample.apply(wavenumbers, intensities, num_points=3000)

    for center in PEAK_CENTERS_CM1:
        before = np.abs(wavenumbers - center) <= 30.0
        after = np.abs(x - center) <= 30.0
        assert float(x[after][int(np.argmax(y[after]))]) == pytest.approx(
            float(wavenumbers[before][int(np.argmax(intensities[before]))]), abs=5.0
        )
        assert y[after].max() == pytest.approx(intensities[before].max(), rel=0.01)


def test_resample_handles_a_descending_input_axis():
    wavenumbers, intensities = synthetic_spectrum()

    x, y = resample.apply(wavenumbers[::-1], intensities[::-1], num_points=500)

    assert x[0] < x[-1]
    assert y.max() == pytest.approx(intensities.max(), rel=0.05)


def test_resample_requires_exactly_one_of_step_or_count():
    wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="exactly one"):
        resample.apply(wavenumbers, intensities)
    with pytest.raises(ValueError, match="exactly one"):
        resample.apply(wavenumbers, intensities, step_cm1=5.0, num_points=100)


def test_resample_rejects_a_step_wider_than_the_range():
    wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="wider than"):
        resample.apply(wavenumbers, intensities, step_cm1=1e6)


def test_resample_rejects_a_grid_that_misses_the_measured_range():
    wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="does not overlap"):
        resample.apply(
            wavenumbers, intensities, num_points=10, min_cm1=8000.0, max_cm1=9000.0
        )
