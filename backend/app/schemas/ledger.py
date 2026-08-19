"""Pydantic schemas for processing ledgers — the append-only, replayable
record of the exact processing steps (+ versioned algorithm/params) applied
to a raw file.

These are wire/DTO shapes only; the persisted row lives in
`app.models.processing_ledger.ProcessingLedger` (frozen, owned elsewhere).
`ProcessingLedger.steps` (JSONB) stores a plain list of `LedgerStep.model_dump()`
dicts (schema_version/raw_file_id live as separate columns on that row).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LedgerStep(BaseModel):
    step_id: UUID
    type: str  # namespaced, e.g. "raman.snv"
    version: str  # semver, matched against LedgerStepDefinition.algorithm_version
    params: dict = Field(default_factory=dict)
    order: int
    applied_at: datetime


class Ledger(BaseModel):
    schema_version: int = 1
    raw_file_id: UUID
    steps: list[LedgerStep] = Field(default_factory=list)
