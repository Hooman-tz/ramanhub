import numpy as np
import pytest

from app.processing.algorithms import snv


def test_snv_normalizes_mean_and_std():
    rng = np.random.default_rng(42)
    spectrum = rng.normal(loc=50, scale=10, size=200)

    result = snv.apply(spectrum)

    assert result.mean() == pytest.approx(0, abs=1e-8)
    assert result.std(ddof=0) == pytest.approx(1, abs=1e-6)


def test_snv_respects_ddof_param():
    rng = np.random.default_rng(1)
    spectrum = rng.normal(loc=0, scale=5, size=50)

    result = snv.apply(spectrum, ddof=1)

    assert result.std(ddof=1) == pytest.approx(1, abs=1e-6)


def test_snv_zero_std_raises_value_error():
    spectrum = np.full(10, 5.0)
    with pytest.raises(ValueError):
        snv.apply(spectrum)


def test_snv_version_is_a_string():
    assert isinstance(snv.VERSION, str)
    assert snv.VERSION
