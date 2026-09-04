"""Peak detection and the NNLS unmixing solver — pure maths, no database.

Both modules under test are deliberately free of `Session`/ORM types, which is
what lets these run as fast synthetic tests. The unmixing cases in particular
encode the pitfalls that make a deconvolution quietly wrong rather than
obviously broken: gain differences, DC pedestals, and collinear components.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.discovery.library_match import (
    COLLINEAR_COSINE,
    _prepare_reference_column,
    solve_unmix,
)
from app.processing.peaks import (
    PEAK_BIN_WIDTH_CM1,
    bin_peak,
    bin_peaks,
    detect_peaks,
    neighbor_bins,
)

GRID = np.linspace(100.0, 2000.0, 1900)


def gaussian(centre: float, amplitude: float, width: float, x: np.ndarray = GRID) -> np.ndarray:
    return amplitude * np.exp(-0.5 * ((x - centre) / width) ** 2)


def three_band_spectrum() -> np.ndarray:
    return gaussian(512, 50, 8) + gaussian(1085, 100, 6) + gaussian(1600, 70, 10)


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------


def test_finds_every_band_and_ranks_the_tallest_first():
    rng = np.random.default_rng(0)
    profile = detect_peaks(GRID, three_band_spectrum() + rng.normal(0, 1.0, GRID.size))

    positions = sorted(p.cm1 for p in profile.peaks)
    assert len(positions) == 3
    for expected, found in zip([512, 1085, 1600], positions):
        assert abs(found - expected) < 2.0

    assert profile.primary_peak_cm1 == pytest.approx(1085, abs=2.0)
    assert profile.peaks[0].rel_height == pytest.approx(1.0)


def test_pure_noise_yields_essentially_nothing():
    """A noise-relative threshold must not manufacture bands out of noise.

    Junk peaks are not cosmetic here: they land in `binned_cm1`, and a library
    entry with junk bins overlaps every query, defeating the prefilter.
    """
    rng = np.random.default_rng(7)
    profile = detect_peaks(GRID, rng.normal(0, 1.0, GRID.size))
    assert len(profile.peaks) <= 2


def test_fluorescence_ramp_does_not_change_which_band_is_strongest():
    """Raw intensity ranking on a sloped spectrum returns the top of the ramp."""
    rng = np.random.default_rng(1)
    clean = three_band_spectrum() + rng.normal(0, 0.3, GRID.size)
    ramp = 800 * np.exp(-(GRID - 100) / 900) + 500

    flat = detect_peaks(GRID, clean)
    sloped = detect_peaks(GRID, clean + ramp)

    assert sloped.primary_peak_cm1 == pytest.approx(flat.primary_peak_cm1, abs=2.0)
    assert {round(p.cm1) for p in sloped.peaks} >= {512, 1085, 1600} - {0}


def test_a_pedestal_lowers_peak_to_background_without_moving_peaks():
    rng = np.random.default_rng(2)
    clean = three_band_spectrum() + rng.normal(0, 0.3, GRID.size)
    raised = detect_peaks(GRID, clean + 5000.0)
    base = detect_peaks(GRID, clean)

    assert raised.peak_to_background < base.peak_to_background
    assert raised.primary_peak_cm1 == pytest.approx(base.primary_peak_cm1, abs=2.0)


def test_minor_band_survives_on_high_snr_data_and_is_dropped_in_noise():
    """The threshold scales with measured noise, which is the whole point."""
    weak = three_band_spectrum() + gaussian(900, 3.0, 6)  # 3% of the primary
    rng = np.random.default_rng(3)

    quiet = detect_peaks(GRID, weak + rng.normal(0, 0.05, GRID.size))
    noisy = detect_peaks(GRID, weak + rng.normal(0, 1.0, GRID.size))

    assert any(abs(p.cm1 - 900) < 5 for p in quiet.peaks)
    assert not any(abs(p.cm1 - 900) < 5 for p in noisy.peaks)


def test_flat_spectrum_is_not_a_division_by_zero():
    profile = detect_peaks(GRID, np.zeros(GRID.size))
    assert profile.peaks == []
    assert profile.primary_peak_cm1 is None
    # `inf` is not valid JSON and would fail serialization at the API edge.
    assert np.isfinite(profile.peak_to_background)


def test_mismatched_array_lengths_are_rejected():
    with pytest.raises(ValueError):
        detect_peaks(GRID, np.zeros(GRID.size - 1))


# ---------------------------------------------------------------------------
# binning
# ---------------------------------------------------------------------------


def test_bins_are_deterministic_deduped_and_sorted():
    profile = detect_peaks(GRID, three_band_spectrum())
    bins = bin_peaks(profile.peaks)
    assert bins == sorted(set(bins))
    assert bin_peaks(profile.peaks) == bins


def test_neighbor_bins_span_the_tolerance_either_side_of_a_bin_edge():
    """A band landing exactly on a bucket edge must still be findable."""
    assert bin_peak(400.0) == int(400.0 / PEAK_BIN_WIDTH_CM1)
    fan = neighbor_bins(400.0, tolerance_cm1=8.0)
    assert bin_peak(392.1) in fan
    assert bin_peak(407.9) in fan
    assert fan == sorted(set(fan))


def test_a_peak_just_across_a_bin_edge_is_still_covered_by_the_query_fan():
    left = bin_peak(399.9)
    right = bin_peak(400.1)
    fan = neighbor_bins(400.0, tolerance_cm1=8.0)
    assert left in fan and right in fan


# ---------------------------------------------------------------------------
# unmixing
# ---------------------------------------------------------------------------

UGRID = np.linspace(200.0, 1800.0, 512)


def _a() -> np.ndarray:
    return gaussian(500, 100, 10, UGRID) + gaussian(1200, 60, 12, UGRID)


def _b() -> np.ndarray:
    return gaussian(800, 90, 9, UGRID) + gaussian(1450, 120, 11, UGRID)


def _solve(observed, columns, names):
    return solve_unmix(
        UGRID, observed, [_prepare_reference_column(c) for c in columns], names
    )


def _expected_weight(major: np.ndarray, minor: np.ndarray, f: float) -> float:
    """Columns are L2-normalized, so the weight is a spectral-energy fraction.

    Feeding in `f*major + (1-f)*minor` returns
    `f||major|| / (f||major|| + (1-f)||minor||)`, NOT `f`. Encoding the real
    definition here rather than asserting 0.7 keeps the test honest about what
    the number means.
    """
    nm = np.linalg.norm(np.clip(major, 0, None))
    nn = np.linalg.norm(np.clip(minor, 0, None))
    return f * nm / (f * nm + (1 - f) * nn)


def test_recovers_a_two_component_mixture():
    a, b = _a(), _b()
    result = _solve(0.7 * a + 0.3 * b, [a, b], ["A", "B"])

    assert result.weights[0] == pytest.approx(_expected_weight(a, b, 0.7), abs=0.02)
    assert sum(result.weights) == pytest.approx(1.0)
    assert result.r_squared > 0.99


def test_weights_are_invariant_to_reference_gain():
    """Without L2 normalization the 'fraction' tracks detector gain."""
    a, b = _a(), _b()
    observed = 0.7 * a + 0.3 * b

    normal = _solve(observed, [a, b], ["A", "B"])
    amplified = _solve(observed, [a, b * 20.0], ["A", "B"])

    assert amplified.weights[0] == pytest.approx(normal.weights[0], abs=0.01)


def test_a_dc_pedestal_is_absorbed_by_the_offset_column_not_the_components():
    """The regression this guards: NNLS inflating the largest weight to soak
    up a constant background, producing a confident but wrong composition."""
    a, b = _a(), _b()
    clean = _solve(0.7 * a + 0.3 * b, [a, b], ["A", "B"])
    raised = _solve(0.7 * a + 0.3 * b + 500.0, [a, b], ["A", "B"])

    assert raised.weights[0] == pytest.approx(clean.weights[0], abs=0.02)
    assert raised.offset == pytest.approx(500.0, rel=0.05)


def test_a_sloping_background_is_absorbed_by_the_ramp_column():
    a, b = _a(), _b()
    clean = _solve(0.7 * a + 0.3 * b, [a, b], ["A", "B"])
    sloped = _solve(
        0.7 * a + 0.3 * b + np.linspace(0, 400, UGRID.size) + 200.0, [a, b], ["A", "B"]
    )

    assert sloped.weights[0] == pytest.approx(clean.weights[0], abs=0.02)
    assert sloped.offset == pytest.approx(200.0, rel=0.1)
    assert sloped.slope == pytest.approx(400.0, rel=0.1)


def test_collinear_components_are_flagged():
    """Polymorphs are near-duplicates: NNLS splits them arbitrarily and the
    residual still looks excellent. The split must not pass silently."""
    a, b = _a(), _b()
    near_duplicate = gaussian(503, 100, 10, UGRID) + gaussian(1203, 60, 12, UGRID)
    shifted = gaussian(501.5, 100, 10, UGRID) + gaussian(1201.5, 60, 12, UGRID)

    result = _solve(0.7 * shifted + 0.3 * b, [a, near_duplicate, b], ["A", "A'", "B"])

    assert result.collinear_warnings, "an ambiguous split must be reported"
    assert "A" in result.collinear_warnings[0]
    cos = float(
        np.dot(_prepare_reference_column(a), _prepare_reference_column(near_duplicate))
        / (
            np.linalg.norm(_prepare_reference_column(a))
            * np.linalg.norm(_prepare_reference_column(near_duplicate))
        )
    )
    assert cos > COLLINEAR_COSINE


def test_an_irrelevant_reference_gets_no_weight():
    a, b = _a(), _b()
    result = _solve(a, [a, b], ["A", "B"])
    assert result.weights[0] == pytest.approx(1.0, abs=1e-6)
    assert result.weights[1] == pytest.approx(0.0, abs=1e-6)


def test_a_signal_no_reference_explains_is_an_error_not_a_composition():
    result_input = np.zeros(UGRID.size)
    with pytest.raises(ValueError, match="explains"):
        _solve(result_input, [_a()], ["A"])


def test_no_columns_is_rejected():
    with pytest.raises(ValueError):
        solve_unmix(UGRID, _a(), [], [])
