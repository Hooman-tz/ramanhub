"""Canonical hashing and validation for processing ledgers.

`ProcessingLedger` rows are immutable and content-addressed: two ledgers
with the same raw file and the same semantic steps (type/version/params/
order) must hash identically so they can be deduped, while `step_id` and
`applied_at` — which are per-write bookkeeping, not semantic content — are
deliberately excluded from the hash.
"""
from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import Modality
from app.models.field_registry import LedgerStepDefinition
from app.schemas.ledger import LedgerStep


class LedgerValidationError(ValueError):
    """Raised when ledger steps reference an unknown step type/version, or
    supply params that don't satisfy the registered `param_schema`."""


def canonicalize(raw_file_id: UUID, schema_version: int, steps: list[LedgerStep]) -> str:
    """Return the canonical JSON string a ledger's hash is computed over.

    Sorted keys, no whitespace, steps ordered by `order`, and only the
    semantic fields (`type`/`version`/`params`/`order`) of each step —
    `step_id`/`applied_at` are excluded on purpose. `raw_file_id` and
    `schema_version` are included so ledgers are content-addressed per raw
    file (two different raw files that happen to use identical steps must
    NOT collide onto the same `ledger_hash`, since `ledger_hash` is globally
    unique across `processing_ledgers`).
    """
    payload = {
        "raw_file_id": str(raw_file_id),
        "schema_version": schema_version,
        "steps": [
            {
                "type": step.type,
                "version": step.version,
                "params": step.params,
                "order": step.order,
            }
            for step in sorted(steps, key=lambda s: s.order)
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def compute_ledger_hash(raw_file_id: UUID, schema_version: int, steps: list[LedgerStep]) -> str:
    """sha256 hex digest of `canonicalize(...)`."""
    canonical = canonicalize(raw_file_id, schema_version, steps)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_JSON_SCHEMA_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "number": (int, float),
    "integer": (int,),
    "string": (str,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _validate_params_against_schema(params: dict, schema: dict, step_type: str) -> None:
    """Pragmatic, structural param check: required keys present, and types
    roughly match `schema["properties"][key]["type"]` where declared. Not a
    full JSON-Schema implementation — that's deliberate, per spec."""
    if not schema:
        return

    required = schema.get("required", [])
    for key in required:
        if key not in params:
            raise LedgerValidationError(f"{step_type}: missing required param {key!r}")

    properties = schema.get("properties", {})
    for key, value in params.items():
        prop_schema = properties.get(key)
        if not prop_schema:
            continue
        expected_type = prop_schema.get("type")
        expected_py_types = _JSON_SCHEMA_TYPE_MAP.get(expected_type)
        if expected_py_types is None:
            continue
        if expected_type == "number" and isinstance(value, bool):
            raise LedgerValidationError(
                f"{step_type}: param {key!r} expected type 'number', got 'boolean'"
            )
        if not isinstance(value, expected_py_types):
            raise LedgerValidationError(
                f"{step_type}: param {key!r} expected type {expected_type!r}, "
                f"got {type(value).__name__!r}"
            )


def validate_ledger_steps(steps: list[LedgerStep], modality: Modality | str, db: Session) -> None:
    """Validate every step against the `LedgerStepDefinition` registry for
    `modality`: the (type, version) pair must be a known, seeded row, and
    `params` must satisfy that row's `param_schema`.

    Raises `LedgerValidationError` (a `ValueError` subclass) on any failure —
    callers (routers) should catch this and translate it to a 422 response.
    """
    modality_value = Modality(modality) if not isinstance(modality, Modality) else modality

    for step in steps:
        definition = (
            db.query(LedgerStepDefinition)
            .filter_by(modality=modality_value, step_type=step.type, algorithm_version=step.version)
            .one_or_none()
        )
        if definition is None:
            raise LedgerValidationError(
                f"Unknown or unversioned processing step: type={step.type!r} "
                f"version={step.version!r} modality={modality_value.value!r}"
            )
        _validate_params_against_schema(step.params, definition.param_schema, step.type)
