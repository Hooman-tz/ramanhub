from __future__ import annotations

import numpy as np
import pytest

from app.raman_contract import canonicalize_raman_arrays


def test_canonicalize_sorts_axis_and_averages_duplicate_wavenumbers():
    x, y, repairs = canonicalize_raman_arrays(
        np.array([400.0, 100.0, 100.0, 250.0]),
        np.array([4.0, 1.0, 3.0, 2.0]),
    )

    np.testing.assert_allclose(x, [100.0, 250.0, 400.0])
    np.testing.assert_allclose(y, [2.0, 2.0, 4.0])
    assert repairs == ["wavenumbers_sorted_ascending", "duplicate_wavenumbers_averaged"]


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (np.array([100.0]), np.array([1.0])),
        (np.array([100.0, np.nan]), np.array([1.0, 2.0])),
        (np.array([100.0, 200.0]), np.array([1.0, np.inf])),
        (np.array([100.0, 200.0]), np.array([1.0])),
    ],
)
def test_canonicalize_rejects_noncanonical_array_shapes_or_values(x, y):
    with pytest.raises(ValueError):
        canonicalize_raman_arrays(x, y)