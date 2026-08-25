"""Non-persisting pipeline evaluation, for previewing a step's effect before
committing it.

## Why this exists rather than reusing `processing.cache.get_or_compute`

`get_or_compute` deliberately refuses to run for a ledger that has not been
persisted first: its whole contract is a read-through cache keyed by a
`ProcessingLedger` row's content hash, and it needs that row's id for the
`ProcessedCache` foreign key. Preview has the opposite requirement — it must
compute the arrays while writing *nothing*.

That is not a technicality. A user building a pipeline changes a parameter
several times per step before settling; routing that through the persisting
path would write a `ProcessingLedger` row and a `ProcessedCache` blob for
every intermediate pipeline they clicked through on the way to the one they
meant. `PipelineBuilder` on the frontend already avoids this for ledgers by
editing a local draft and committing once; this module is the server-side
half of that same decision.

The tradeoff accepted: preview recomputes from raw every call and benefits
from no caching. That is the right way round — previews are transient and
mostly distinct, so a cache would mostly miss while still paying the write
cost, and the numerics are milliseconds on a normally-sized spectrum.

Validation is deliberately identical to the commit path (`validate_ledger_steps`
against the seeded `LedgerStepDefinition` registry). A preview that accepted
a pipeline the ledger would later reject would be a trap: the user would see
a result, press Apply, and get a 422.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
from sqlalchemy.orm import Session

from app.models.raw_file import RawFile
from app.processing.algorithms.registry import apply_step, get_algorithm
from app.processing.ledger import LedgerValidationError, validate_ledger_steps
from app.schemas.ledger import LedgerStep
from app.spectra_io import load_raw_spectrum

# Upper bound on a previewed pipeline. Real pipelines are 1-6 steps; this is
# a backstop so one request can't pin the instance replaying a pathological
# chain, matching the reasoning behind MAX_SPECTRA_PER_ANALYSIS.
MAX_PREVIEW_STEPS = 20


class PreviewError(ValueError):
    """A previewed pipeline that could not be built or replayed. Routers
    translate this to a 422 — it always means bad client input (unknown step
    type, params failing the schema, or a step that can't run on this
    spectrum), never a server fault."""


def build_steps(raw_steps: list[tuple[str, dict, int]]) -> list[LedgerStep]:
    """Turn `(type, params, order)` triples into validated `LedgerStep`s with
    server-resolved versions — the same resolution the commit path does, so
    the client never has to know internal version numbers."""
    if len(raw_steps) > MAX_PREVIEW_STEPS:
        raise PreviewError(
            f"Too many steps to preview: {len(raw_steps)} (limit {MAX_PREVIEW_STEPS})"
        )

    now = datetime.now(UTC)
    steps: list[LedgerStep] = []
    for step_type, params, order in raw_steps:
        try:
            _, version = get_algorithm(step_type)
        except KeyError as exc:
            raise PreviewError(str(exc)) from exc
        steps.append(
            LedgerStep(
                step_id=uuid4(),
                type=step_type,
                version=version,
                params=params or {},
                order=order,
                applied_at=now,
            )
        )
    return steps


def compute_preview(
    raw_file: RawFile,
    steps: list[LedgerStep],
    db: Session,
) -> tuple[np.ndarray, np.ndarray]:
    """Replay `steps` against `raw_file`'s raw arrays and return the result.

    Writes nothing — no ledger row, no cache row, no storage object.
    """
    try:
        validate_ledger_steps(steps, raw_file.modality, db)
    except LedgerValidationError as exc:
        raise PreviewError(str(exc)) from exc

    wavenumbers, intensities = load_raw_spectrum(raw_file)
    for step in sorted(steps, key=lambda s: s.order):
        try:
            wavenumbers, intensities = apply_step(
                step.type, wavenumbers, intensities, step.params
            )
        except Exception as exc:
            # Params can be individually schema-valid and still fail together
            # or against this particular spectrum: a crop window that falls
            # outside the measured range, a Savitzky-Golay window longer than
            # the array, a resample grid with no overlap. That is a client
            # error about THIS spectrum, not a server fault, so it surfaces
            # as a 422 naming the step rather than a 500.
            raise PreviewError(f"Step {step.order + 1} ({step.type}) failed: {exc}") from exc

    return wavenumbers, intensities
