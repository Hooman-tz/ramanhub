import numpy as np
import pytest

from app.processing.algorithms import despike

from ._synthetic import PEAK_CENTERS_CM1, peak_indices, synthetic_spectrum


def test_removes_injected_spikes():
    spike_at = (150, 400, 720)
    _wavenumbers, spiked = synthetic_spectrum(
        spike_indices=spike_at, spike_amplitude=800.0, noise_sigma=0.5
    )

    despiked = despike.apply(spiked)

    for index in spike_at:
        # Each spike was +800 on a spectrum whose real bands top out near
        # 100; anything still near that height was not removed.
        assert despiked[index] < 200.0


def test_removes_a_spike_sitting_on_a_band_flank():
    """The case a run-length-only width test gets wrong: the spike's
    differences merge into the flank's, and a naive implementation discards
    both together and leaves the spike in place."""
    wavenumbers, intensities = synthetic_spectrum(noise_sigma=0.5)
    flank = peak_indices(wavenumbers)[0] - 8
    intensities[flank] += 800.0

    despiked = despike.apply(intensities)

    assert despiked[flank] < 200.0


def test_preserves_real_peaks():
    wavenumbers, intensities = synthetic_spectrum(noise_sigma=0.5)

    despiked = despike.apply(intensities)

    for index in peak_indices(wavenumbers):
        assert despiked[index] == pytest.approx(intensities[index], rel=0.05)


def test_clean_spectrum_is_left_untouched():
    """On near-noiseless data the MAD collapses to the noise floor, so a
    band's own curvature scores in the dozens — the prominence criterion is
    the only thing keeping real peaks intact here."""
    _wavenumbers, intensities = synthetic_spectrum(noise_sigma=0.05)

    despiked = despike.apply(intensities)

    np.testing.assert_allclose(despiked, intensities)


def test_noisy_spectrum_without_spikes_is_left_essentially_alone():
    _wavenumbers, intensities = synthetic_spectrum(noise_sigma=2.0)

    despiked = despike.apply(intensities)

    assert np.abs(despiked - intensities).max() < 20.0


def test_repair_follows_the_local_slope():
    """Interpolating across the gap, rather than averaging a neighbourhood,
    is what keeps a repaired flank from being notched."""
    wavenumbers, intensities = synthetic_spectrum()
    flank = peak_indices(wavenumbers)[0] - 8
    spiked = intensities.copy()
    spiked[flank] += 800.0

    despiked = despike.apply(spiked)

    # Within a few percent of the true value — the residual is the linear
    # interpolant's curvature error across a convex flank, not a notch.
    assert despiked[flank] == pytest.approx(intensities[flank], rel=0.05)
    # And much closer than averaging a neighbourhood would have been.
    neighbourhood_mean = np.concatenate(
        [intensities[flank - 5 : flank], intensities[flank + 1 : flank + 6]]
    ).mean()
    truth = intensities[flank]
    assert abs(despiked[flank] - truth) < abs(neighbourhood_mean - truth)


def test_wide_artifact_is_left_alone_by_default_but_removed_when_max_width_is_raised():
    _wavenumbers, intensities = synthetic_spectrum(noise_sigma=0.5)
    intensities[500:508] += 900.0  # 8 points wide — too wide for a cosmic ray

    assert despike.apply(intensities)[500:508].max() > 500.0
    assert despike.apply(intensities, max_width=12)[500:508].max() < 500.0


def test_prominence_criterion_can_be_disabled():
    """With the physical scale removed, only the statistical criteria
    remain — which on clean data does clip real band apexes. Exercised here
    so the tradeoff of setting the ratio to 0 is explicit."""
    wavenumbers, intensities = synthetic_spectrum(noise_sigma=0.05)

    permissive = despike.apply(intensities, min_prominence_ratio=0.0)

    apex = peak_indices(wavenumbers)[0]
    assert permissive[apex] < intensities[apex]


def test_constant_spectrum_is_returned_unchanged():
    # A zero MAD would divide by zero in a naive modified Z-score.
    flat = np.full(50, 7.0)

    assert np.array_equal(despike.apply(flat), flat)


def test_very_short_spectrum_is_returned_unchanged():
    short = np.array([1.0, 9.0])

    assert np.array_equal(despike.apply(short), short)


def test_rejects_non_positive_max_width():
    _wavenumbers, intensities = synthetic_spectrum()

    with pytest.raises(ValueError, match="max_width"):
        despike.apply(intensities, max_width=0)


def test_band_centres_are_unchanged_by_a_spike_elsewhere():
    wavenumbers, intensities = synthetic_spectrum(noise_sigma=0.5)
    spiked = intensities.copy()
    spiked[600] += 1000.0

    despiked = despike.apply(spiked)

    for center in PEAK_CENTERS_CM1:
        window = np.abs(wavenumbers - center) <= 30.0
        np.testing.assert_allclose(despiked[window], intensities[window], rtol=1e-6)
