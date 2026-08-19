"""Tests for app.spectra_io: compute_snr and lttb_downsample. These are
foundational utilities Modules 3/4 build on, so they're tested in isolation
before anything else depends on them."""
from __future__ import annotations

import numpy as np

from app.spectra_io import compute_snr, lttb_downsample


class TestComputeSnr:
    def test_higher_peak_yields_higher_snr(self):
        rng = np.random.default_rng(0)
        baseline = rng.normal(0, 1.0, 500)
        low_peak = baseline.copy()
        low_peak[250] += 5
        high_peak = baseline.copy()
        high_peak[250] += 50

        assert compute_snr(high_peak) > compute_snr(low_peak)

    def test_flat_array_returns_none(self):
        flat = np.full(100, 5.0)
        assert compute_snr(flat) is None

    def test_too_short_returns_none(self):
        assert compute_snr(np.array([1.0])) is None
        assert compute_snr(np.array([])) is None

    def test_noisier_array_yields_lower_snr_for_same_peak(self):
        rng = np.random.default_rng(1)
        quiet = rng.normal(0, 0.1, 500)
        noisy = rng.normal(0, 5.0, 500)
        quiet[250] += 20
        noisy[250] += 20

        assert compute_snr(quiet) > compute_snr(noisy)


class TestLttbDownsample:
    def test_noop_when_n_out_exceeds_length(self):
        x = np.arange(10, dtype=float)
        y = np.sin(x)
        rx, ry = lttb_downsample(x, y, 20)
        assert np.array_equal(rx, x)
        assert np.array_equal(ry, y)

    def test_output_length_matches_request(self):
        x = np.arange(1000, dtype=float)
        y = np.sin(x / 10)
        rx, ry = lttb_downsample(x, y, 100)
        assert rx.shape[0] == 100
        assert ry.shape[0] == 100

    def test_keeps_first_and_last_point(self):
        x = np.arange(1000, dtype=float)
        y = np.sin(x / 10)
        rx, ry = lttb_downsample(x, y, 50)
        assert rx[0] == x[0]
        assert rx[-1] == x[-1]
        assert ry[0] == y[0]
        assert ry[-1] == y[-1]

    def test_preserves_a_sharp_peak(self):
        # A single sharp spike among a flat baseline -- LTTB should keep it
        # (that's the whole point of the algorithm), not average it away.
        n = 2000
        x = np.arange(n, dtype=float)
        y = np.zeros(n)
        y[1000] = 100.0
        _rx, ry = lttb_downsample(x, y, 100)
        assert ry.max() > 50.0  # the spike survived, even if not at full height

    def test_x_is_monotonic_in_output(self):
        x = np.arange(500, dtype=float)
        y = np.cos(x / 5)
        rx, _ = lttb_downsample(x, y, 80)
        assert np.all(np.diff(rx) > 0)
