import numpy as np
import pytest

from app.processing.algorithms import msc


def test_msc_recovers_reference_from_known_linear_transform():
    rng = np.random.default_rng(0)
    reference = np.linspace(1, 10, 100) + rng.normal(0, 0.01, 100)
    slope, intercept = 2.5, 1.3
    spectrum = slope * reference + intercept

    corrected = msc.apply(
        spectrum, reference_source={"type": "array", "values": reference.tolist()}
    )

    assert corrected == pytest.approx(reference, abs=1e-6)


def test_msc_missing_reference_source_raises():
    with pytest.raises(ValueError):
        msc.apply(np.array([1.0, 2.0, 3.0]))


def test_msc_wrong_reference_type_raises():
    with pytest.raises(ValueError):
        msc.apply(np.array([1.0, 2.0, 3.0]), reference_source={"type": "raw_file_id", "value": "x"})


def test_msc_mismatched_length_raises():
    with pytest.raises(ValueError):
        msc.apply(
            np.array([1.0, 2.0, 3.0]),
            reference_source={"type": "array", "values": [1.0, 2.0]},
        )
