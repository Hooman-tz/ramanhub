"""Pydantic schemas for the ingestion pipeline.

`ExtractedMetadata` is the single typed shape that both deterministic vendor
parsers and the LLM fallback must produce. It is a deliberate security
boundary: `extra="forbid"` means any unexpected top-level key coming back
from an LLM tool-call is rejected outright (never silently merged into the
DB), and `raw_extra_fields` is bounded to flat scalar values so LLM output
can never smuggle nested/structured data into storage.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bounds for the catch-all bucket — deliberately small. This is not meant to
# be a general-purpose payload channel, just a place for a handful of extra
# scalar facts a parser/LLM was confident about but that don't map to a
# known field.
MAX_RAW_EXTRA_FIELDS = 20
MAX_RAW_EXTRA_VALUE_STR_LEN = 500
MAX_RAW_EXTRA_KEY_LEN = 100


class ExtractedMetadata(BaseModel):
    """Structured metadata extracted from a raw file's vendor header, either
    by a deterministic parser or the LLM fallback. Every producer of this
    shape (parsers, `llm_fallback`) must go through `model_validate` so
    malformed data is rejected before it ever reaches the database.
    """

    model_config = ConfigDict(extra="forbid")

    modality: str = "raman"
    instrument_vendor: str | None = None
    instrument_model: str | None = None
    laser_wavelength_nm: float | None = None
    laser_power_mw: float | None = None
    integration_time_ms: float | None = None
    accumulations: int | None = None
    spectral_range_cm1: str | None = None  # stored as "min-max"
    resolution_cm1: float | None = None
    acquisition_datetime: str | None = None
    sample_description: str | None = None
    grating_lines_mm: float | None = None
    objective_magnification: float | None = None
    raw_extra_fields: dict[str, str | float | int] = Field(default_factory=dict)

    @field_validator("raw_extra_fields")
    @classmethod
    def _bound_raw_extra_fields(
        cls, value: dict[str, str | float | int]
    ) -> dict[str, str | float | int]:
        if len(value) > MAX_RAW_EXTRA_FIELDS:
            raise ValueError(
                f"raw_extra_fields has {len(value)} keys, max is {MAX_RAW_EXTRA_FIELDS}"
            )
        for key, val in value.items():
            if len(key) > MAX_RAW_EXTRA_KEY_LEN:
                raise ValueError(f"raw_extra_fields key too long: {key!r}")
            if isinstance(val, str) and len(val) > MAX_RAW_EXTRA_VALUE_STR_LEN:
                raise ValueError(f"raw_extra_fields value for {key!r} too long")
        return value


class IngestionJobOut(BaseModel):
    """Response shape for GET /ingestion-jobs/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_file_id: uuid.UUID
    status: str
    parser_used: str | None = None
    header_hash: str | None = None
    extracted_metadata_raw: dict[str, Any] | None = None
    sanity_check_flags: dict[str, Any] | None = None
    extracted_metadata_confirmed: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    confirmed_at: datetime | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, value: Any) -> Any:
        # SQLAlchemy enum columns yield Python enum members; the API contract
        # is a plain string.
        return value.value if hasattr(value, "value") else value


class ConfirmMetadataRequest(BaseModel):
    """Body for PATCH /ingestion-jobs/{id} — the only write path into
    `extracted_metadata_confirmed`. Reuses `ExtractedMetadata`'s strict
    validation so a confirmed edit can't smuggle unexpected fields either.
    """

    model_config = ConfigDict(extra="forbid")

    metadata: ExtractedMetadata
