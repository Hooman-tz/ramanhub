"""Maps namespaced ledger step types (e.g. "raman.snv") to their
implementation, version, and parameter schema.

This is the single source of truth for "which Python function implements
step type X at the version currently shipped, and what params does it
accept". Three things read from it:

- `processing/cache.py` — replays a ledger's steps against a spectrum
- `app/seed/seed_data.py` — writes the `LedgerStepDefinition` rows that
  `processing/ledger.py` validates submitted ledgers against, so the DB-side
  registry can never drift from the code-side one
- `app/routers/processing.py` — serves the catalog the frontend's pipeline
  builder renders its param inputs from

## Two calling conventions

Most steps only transform intensities, and are written as
`apply(intensities, **params) -> intensities` (`kind="intensity"`). Steps
that need the wavenumber axis — area normalization, peak normalization —
or that change it — cropping, resampling — are written as
`apply(wavenumbers, intensities, **params) -> (wavenumbers, intensities)`
(`kind="axis_aware"`). `apply_step()` below normalizes both to the
axis-aware shape so callers never branch on it.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from app.processing.algorithms import (
    baseline_als,
    baseline_polynomial,
    crop,
    despike,
    fluorescence_suppression,
    msc,
    normalize_area,
    normalize_minmax,
    normalize_peak,
    normalize_vector,
    resample,
    savitzky_golay,
    snv,
)


@dataclass(frozen=True)
class AlgorithmSpec:
    """Everything the platform knows about one processing step type."""

    step_type: str
    apply: Callable[..., Any]
    version: str
    label: str
    category: Literal["despiking", "smoothing", "baseline", "normalization", "axis"]
    description: str
    param_schema: dict
    kind: Literal["intensity", "axis_aware"] = "intensity"

    @property
    def transforms_axis(self) -> bool:
        """True if this step can change the length/values of the wavenumber
        axis (crop, resample) — the UI warns about these because they
        invalidate length-matched params of later steps (e.g. MSC's inline
        reference array)."""
        return self.step_type in _AXIS_TRANSFORMING


_AXIS_TRANSFORMING = frozenset({"raman.crop", "raman.resample"})


def _spec(module, **overrides) -> AlgorithmSpec:
    """Build a spec from an algorithm module's module-level constants, so
    each algorithm declares its own metadata next to its implementation."""
    return AlgorithmSpec(
        step_type=module.STEP_TYPE,
        apply=module.apply,
        version=module.VERSION,
        label=module.LABEL,
        category=module.CATEGORY,
        description=module.DESCRIPTION,
        param_schema=module.PARAM_SCHEMA,
        **overrides,
    )


ALGORITHM_SPECS: tuple[AlgorithmSpec, ...] = (
    _spec(despike),
    _spec(savitzky_golay),
    _spec(fluorescence_suppression),
    _spec(baseline_als),
    _spec(baseline_polynomial, kind="axis_aware"),
    _spec(snv),
    _spec(msc),
    _spec(normalize_minmax),
    _spec(normalize_vector),
    _spec(normalize_area, kind="axis_aware"),
    _spec(normalize_peak, kind="axis_aware"),
    _spec(crop, kind="axis_aware"),
    _spec(resample, kind="axis_aware"),
)

ALGORITHM_REGISTRY: dict[str, AlgorithmSpec] = {spec.step_type: spec for spec in ALGORITHM_SPECS}


def get_spec(step_type: str) -> AlgorithmSpec:
    """Return the `AlgorithmSpec` for `step_type`, or raise `KeyError` with a
    clear message if the step type is unknown to this codebase."""
    try:
        return ALGORITHM_REGISTRY[step_type]
    except KeyError as exc:
        raise KeyError(f"Unknown processing algorithm step type: {step_type!r}") from exc


def get_algorithm(step_type: str) -> tuple[Callable[..., Any], str]:
    """Return `(callable, version)` for `step_type`. Kept as the narrow
    lookup used by `routers/ledgers.py` to resolve a client-supplied step
    type to the version this codebase ships."""
    spec = get_spec(step_type)
    return spec.apply, spec.version


def apply_step(
    step_type: str,
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    params: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply one step, normalizing both calling conventions to
    `(wavenumbers, intensities) -> (wavenumbers, intensities)`."""
    spec = get_spec(step_type)
    if spec.kind == "axis_aware":
        return spec.apply(wavenumbers, intensities, **params)
    return wavenumbers, spec.apply(intensities, **params)
