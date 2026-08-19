"""Maps namespaced ledger step types (e.g. "raman.snv") to their
`(callable, version)` implementation.

This is the single source of truth for "which Python function implements
step type X at the version currently shipped" — `processing/ledger.py`
validates against `LedgerStepDefinition` rows (the DB-side registry of
*known* versions), while this module resolves *this codebase's* callable for
replaying a step.
"""
from __future__ import annotations

from collections.abc import Callable

from app.processing.algorithms import fluorescence_suppression, msc, snv

ALGORITHM_REGISTRY: dict[str, tuple[Callable[..., object], str]] = {
    "raman.snv": (snv.apply, snv.VERSION),
    "raman.msc": (msc.apply, msc.VERSION),
    "raman.fluorescence_suppression.airpls": (
        fluorescence_suppression.apply,
        fluorescence_suppression.VERSION,
    ),
}


def get_algorithm(step_type: str) -> tuple[Callable[..., object], str]:
    """Return `(callable, version)` for `step_type`, or raise `KeyError` with
    a clear message if the step type is unknown to this codebase."""
    try:
        return ALGORITHM_REGISTRY[step_type]
    except KeyError as exc:
        raise KeyError(f"Unknown processing algorithm step type: {step_type!r}") from exc
