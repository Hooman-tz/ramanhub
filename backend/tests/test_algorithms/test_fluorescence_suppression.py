import numpy as np

from app.processing.algorithms import fluorescence_suppression as fs


def _gaussian(x: np.ndarray, center: float, amplitude: float, width: float) -> np.ndarray:
    return amplitude * np.exp(-((x - center) ** 2) / (2 * width**2))


def _synthetic_spectrum(seed: int = 1):
    x = np.arange(1000, dtype=float)
    baseline = 0.0003 * (x - 500) ** 2 + 30  # smooth polynomial baseline
    peak_centers = [200, 500, 800]
    signal = np.zeros_like(x)
    for center in peak_centers:
        signal += _gaussian(x, center, amplitude=80, width=5)
    noise = np.random.default_rng(seed).normal(0, 0.3, size=x.shape)
    spectrum = baseline + signal + noise
    return x, spectrum, peak_centers


def test_airpls_preserves_peak_positions():
    _x, spectrum, peak_centers = _synthetic_spectrum()

    corrected = fs.apply(spectrum, lambda_=1e5, max_iter=20)

    for center in peak_centers:
        window = corrected[center - 10 : center + 10]
        peak_idx = center - 10 + int(np.argmax(window))
        assert abs(peak_idx - center) <= 3


def test_airpls_substantially_reduces_baseline_magnitude():
    x, spectrum, peak_centers = _synthetic_spectrum()

    corrected = fs.apply(spectrum, lambda_=1e5, max_iter=20)

    non_peak_mask = np.ones_like(x, dtype=bool)
    for center in peak_centers:
        non_peak_mask[max(0, center - 20) : center + 20] = False

    raw_magnitude = np.abs(spectrum[non_peak_mask]).mean()
    corrected_magnitude = np.abs(corrected[non_peak_mask]).mean()

    assert corrected_magnitude < raw_magnitude * 0.3


def test_airpls_version_is_a_string():
    assert isinstance(fs.VERSION, str)
    assert fs.VERSION
