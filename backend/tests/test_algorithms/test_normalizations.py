import numpy as np
import pytest

from app.processing.algorithms import (
    normalize_area,
    normalize_minmax,
    normalize_peak,
    normalize_vector,
)

from ._synthetic import PEAK_CENTERS_CM1, synthetic_spectrum

# ---------------------------------------------------------------------------
# Min-max
# ---------------------------------------------------------------------------


def test_minmax_maps_onto_unit_interval():
    _wavenumbers, intensities = synthetic_spectrum()

    normalized = normalize_minmax.apply(intensities)

    assert normalized.min() == pytest.approx(0.0)
    assert normalized.max() == pytest.approx(1.0)


def test_minmax_honours_custom_bounds():
    _wavenumbers, intensities = synthetic_spectrum()

    normalized = normalize_minmax.apply(intensities, lower=-1.0, upper=1.0)

    assert normalized.min() == pytest.approx(-1.0)
    assert normalized.max() == pytest.approx(1.0)


def test_minmax_rejects_constant_spectrum():
    with pytest.raises(ValueError, match="constant"):
        normalize_minmax.apply(np.full(20, 3.0))


def test_minmax_rejects_inverted_bounds():
    _wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="greater than"):
        normalize_minmax.apply(intensities, lower=1.0, upper=0.0)


# ---------------------------------------------------------------------------
# Vector / L2
# ---------------------------------------------------------------------------


def test_vector_gives_unit_norm():
    _wavenumbers, intensities = synthetic_spectrum()

    normalized = normalize_vector.apply(intensities)

    assert float(np.linalg.norm(normalized)) == pytest.approx(1.0)


def test_vector_is_scale_invariant():
    """Two acquisitions of the same sample at different laser powers must
    land on the same unit vector — that's the whole point."""
    _wavenumbers, intensities = synthetic_spectrum()

    np.testing.assert_allclose(
        normalize_vector.apply(intensities), normalize_vector.apply(intensities * 7.5)
    )


def test_vector_rejects_all_zero_spectrum():
    with pytest.raises(ValueError, match="zero norm"):
        normalize_vector.apply(np.zeros(20))


# ---------------------------------------------------------------------------
# Area
# ---------------------------------------------------------------------------


def test_area_gives_unit_integrated_area():
    wavenumbers, intensities = synthetic_spectrum()

    x, normalized = normalize_area.apply(wavenumbers, intensities)

    assert float(np.trapezoid(np.abs(normalized), x)) == pytest.approx(1.0)


def test_area_is_computed_over_the_wavenumber_axis_not_the_index():
    """Unevenly spaced points are the case that separates the two, and they
    are exactly what `raman.crop` and stitched acquisitions produce."""
    x = np.array([100.0, 101.0, 102.0, 200.0, 300.0])
    y = np.array([1.0, 1.0, 1.0, 1.0, 1.0])

    _x, normalized = normalize_area.apply(x, y)

    # Integrating over the axis gives an area of 200 (the span), not 4
    # (n-1 unit-index trapezoids).
    assert normalized[0] == pytest.approx(1.0 / 200.0)


def test_area_handles_descending_wavenumber_axis():
    """Some vendors write wavenumbers high-to-low; naive trapezoidal
    integration over that axis returns a negative area and would flip the
    spectrum's sign."""
    wavenumbers, intensities = synthetic_spectrum()

    _x, normalized = normalize_area.apply(wavenumbers[::-1], intensities[::-1])

    assert normalized.max() > 0


def test_area_rejects_mismatched_array_lengths():
    with pytest.raises(ValueError, match="match in length"):
        normalize_area.apply(np.arange(5, dtype=float), np.arange(4, dtype=float))


# ---------------------------------------------------------------------------
# Peak
# ---------------------------------------------------------------------------


def test_peak_scales_the_named_band_to_one():
    wavenumbers, intensities = synthetic_spectrum()
    target = PEAK_CENTERS_CM1[1]

    _x, normalized = normalize_peak.apply(wavenumbers, intensities, wavenumber=target)

    window = np.abs(wavenumbers - target) <= 10.0
    assert normalized[window].max() == pytest.approx(1.0)


def test_peak_without_a_target_uses_the_global_maximum():
    wavenumbers, intensities = synthetic_spectrum()

    _x, normalized = normalize_peak.apply(wavenumbers, intensities)

    assert normalized.max() == pytest.approx(1.0)


def test_peak_tolerance_absorbs_a_small_calibration_shift():
    """A band centre reported 4 cm-1 off — routine between instruments —
    must still be found."""
    wavenumbers, intensities = synthetic_spectrum()

    _x, normalized = normalize_peak.apply(
        wavenumbers, intensities, wavenumber=PEAK_CENTERS_CM1[1] + 4.0, tolerance=10.0
    )

    assert normalized.max() == pytest.approx(1.0, rel=1e-6)


def test_peak_rejects_a_band_outside_the_measured_range():
    wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="no points within"):
        normalize_peak.apply(wavenumbers, intensities, wavenumber=9000.0, tolerance=5.0)
