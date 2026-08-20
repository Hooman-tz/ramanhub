"""Contract tests for the algorithm registry.

The registry is load-bearing in three directions at once — ledger replay,
the seeded `LedgerStepDefinition` rows that ledgers are validated against,
and the catalog the frontend renders — so these tests check the invariants
that keep those three in sync rather than any single algorithm's maths.
"""
import numpy as np
import pytest

from app.processing.algorithms.registry import (
    ALGORITHM_REGISTRY,
    ALGORITHM_SPECS,
    apply_step,
    get_algorithm,
    get_spec,
)
from app.routers.processing import CATEGORY_ORDER
from app.seed.seed_data import RAMAN_LEDGER_STEPS

from ._synthetic import synthetic_spectrum


def test_every_spec_is_addressable_by_its_step_type():
    assert len(ALGORITHM_REGISTRY) == len(ALGORITHM_SPECS)
    for spec in ALGORITHM_SPECS:
        assert get_spec(spec.step_type) is spec


def test_step_types_are_modality_namespaced():
    """Namespacing by modality from the start is what lets mass-spec and NMR
    steps land alongside these later without a schema rewrite."""
    for spec in ALGORITHM_SPECS:
        assert spec.step_type.startswith("raman.")


def test_every_category_is_known_to_the_catalog_endpoint():
    for spec in ALGORITHM_SPECS:
        assert spec.category in CATEGORY_ORDER


def test_seed_rows_are_generated_from_the_registry():
    """If these ever drift, `validate_ledger_steps` rejects ledgers the code
    can run — the exact failure the derived seed list exists to prevent."""
    seeded = {row["step_type"]: row for row in RAMAN_LEDGER_STEPS}
    assert set(seeded) == set(ALGORITHM_REGISTRY)
    for spec in ALGORITHM_SPECS:
        assert seeded[spec.step_type]["algorithm_version"] == spec.version
        assert seeded[spec.step_type]["param_schema"] == spec.param_schema


def test_unknown_step_type_raises_a_named_error():
    with pytest.raises(KeyError, match="raman.nonexistent"):
        get_spec("raman.nonexistent")
    with pytest.raises(KeyError, match="raman.nonexistent"):
        get_algorithm("raman.nonexistent")


@pytest.mark.parametrize("spec", ALGORITHM_SPECS, ids=lambda s: s.step_type)
def test_every_algorithm_returns_matching_array_lengths(spec):
    """Whichever calling convention a step uses, `apply_step` must hand back
    a (wavenumbers, intensities) pair of equal length — the invariant every
    downstream consumer (cache, chart, SNR, similarity search) relies on."""
    wavenumbers, intensities = synthetic_spectrum(n_points=400, with_background=True)
    params = _representative_params(spec.step_type, wavenumbers, intensities)

    x, y = apply_step(spec.step_type, wavenumbers, intensities, params)

    assert x.size == y.size
    assert np.isfinite(y).all()


@pytest.mark.parametrize(
    "step_type", [s.step_type for s in ALGORITHM_SPECS if not s.transforms_axis]
)
def test_non_axis_steps_leave_the_wavenumbers_untouched(step_type):
    wavenumbers, intensities = synthetic_spectrum(n_points=400, with_background=True)
    params = _representative_params(step_type, wavenumbers, intensities)

    x, _y = apply_step(step_type, wavenumbers, intensities, params)

    np.testing.assert_array_equal(x, wavenumbers)


def test_axis_steps_are_flagged_as_such():
    assert {s.step_type for s in ALGORITHM_SPECS if s.transforms_axis} == {
        "raman.crop",
        "raman.resample",
    }


def _representative_params(step_type: str, wavenumbers, intensities) -> dict:
    """Minimal valid params per step — most take none, a few can't run
    without one."""
    if step_type == "raman.msc":
        return {"reference_source": {"type": "array", "values": intensities.tolist()}}
    if step_type == "raman.crop":
        return {"min_cm1": 400.0, "max_cm1": 2000.0}
    if step_type == "raman.resample":
        return {"num_points": 200}
    return {}
