"""Pydantic schemas for the ingestion pipeline.

`ExtractedMetadata` is the single typed shape that both deterministic vendor
parsers and the LLM fallback must produce. It is a deliberate security
boundary: `extra="forbid"` means any unexpected top-level key coming back
from an LLM tool-call is rejected outright (never silently merged into the
DB), and `raw_extra_fields` is bounded to flat scalar values so LLM output
can never smuggle nested/structured data into storage.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

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

    modality: Literal["raman"] = "raman"
    instrument_vendor: str | None = Field(default=None, max_length=200)
    instrument_model: str | None = Field(default=None, max_length=200)
    # Expected physical ranges live in the modality field registry and become
    # visible QC flags. Hard-rejecting unusual values here would make it
    # impossible for a scientist to preserve and explain a legitimate outlier.
    laser_wavelength_nm: float | None = None
    laser_power_mw: float | None = None
    integration_time_ms: float | None = None
    accumulations: int | None = None
    spectral_range_cm1: str | None = None  # stored as "min-max"
    resolution_cm1: float | None = None
    acquisition_datetime: str | None = Field(default=None, max_length=64)
    sample_description: str | None = Field(default=None, max_length=4_000)
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

    @field_validator("spectral_range_cm1")
    @classmethod
    def _validate_spectral_range(cls, value: str | None) -> str | None:
        if value is None:
            return None
        match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*", value)
        if match is None:
            raise ValueError("spectral_range_cm1 must be formatted as 'min-max'")
        lower, upper = (float(match.group(1)), float(match.group(2)))
        if lower >= upper or lower < -5_000 or upper > 100_000:
            raise ValueError("spectral_range_cm1 must be a plausible ascending Raman range")
        return f"{lower:g}-{upper:g}"


# Upper bounds for a detected layout. A Raman export with more than this many
# traces is a hyperspectral map, not a stack of spectra, and is out of scope
# for the per-trace import path; the bound also stops a confused model from
# asking us to create thousands of draft spectra.
MAX_TRACES = 512
MAX_PREVIEW_ROWS = 40
MAX_PREVIEW_COLUMNS = 25

# Structure detection samples the body in several places rather than only at
# the top. A ten-row window at the head is blind to the things that actually
# distinguish these formats: a stacked-blocks export shows its second block
# hundreds of rows down, a footer marker only appears at the end, and a file
# that changes shape halfway through looks perfectly ordinary from row 0.
PREVIEW_PATCH_ROWS = 6
# Where the extra patches sit, as fractions through the numeric body. A tail
# patch is always appended on top of these.
PREVIEW_PATCH_FRACTIONS = (0.25, 0.50, 0.75)
# Columns shown in the grid for a wide file: the first few, a few from the
# middle, and the last few — enough to tell "axis then N traces" from "N
# traces then junk" without printing 200 columns.
MAX_PREVIEW_SHOWN_COLUMNS = 12
PREVIEW_HEAD_COLUMNS = 5
PREVIEW_MID_COLUMNS = 3
# One float per column is cheap and is the strongest structural signal we
# have without a model, so it covers every column up to this cap.
MAX_NUMERIC_FRACTION_COLUMNS = 512
# Body rows sampled (with a stride, across the whole file) to compute those
# fractions. Strided rather than the first N, so a file whose columns change
# character halfway down is not mischaracterised by its opening.
NUMERIC_FRACTION_SAMPLE_ROWS = 200

# "whitespace" means "split on any run of blank space", which is its own rule
# rather than a single character.
WHITESPACE_DELIMITER = "whitespace"


class TraceSpec(BaseModel):
    """One spectrum inside a raw file.

    `index` is interpreted against the layout's orientation: a column index
    for `column_major`, a data-row index for `row_major`, a block ordinal for
    `stacked_blocks`.
    """

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0, lt=100_000)
    label: str | None = Field(default=None, max_length=200)


class FileLayout(BaseModel):
    """How to read numeric traces out of a text spectral file.

    This is the deterministic contract that structure detection produces and
    array loading consumes. It is deliberately small and fully declarative:
    whether it came from a heuristic, an LLM, or the user typing it in, the
    same code applies it, and the result is always verified against
    `raman_contract.canonicalize_raman_arrays` before anything is stored.
    """

    model_config = ConfigDict(extra="forbid")

    orientation: Literal["column_major", "row_major", "stacked_blocks"] = "column_major"
    delimiter: str = Field(default=WHITESPACE_DELIMITER, max_length=12)
    decimal_separator: Literal[".", ","] = "."
    comment_prefixes: list[str] = Field(default_factory=lambda: ["#"])
    # Rows of preamble to skip before the numeric body. For `row_major` this
    # counts rows before the wavenumber-axis row.
    header_rows: int = Field(default=0, ge=0, le=10_000)
    # Column (column_major) or data-row (row_major) holding the wavenumber
    # axis. Ignored for `stacked_blocks`, where every block carries its own.
    x_index: int = Field(default=0, ge=0, lt=100_000)
    # Column (row_major) carrying each trace's label. None means unlabelled.
    label_index: int | None = Field(default=None, ge=0, lt=100_000)
    traces: list[TraceSpec] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["heuristic", "llm", "user"] = "heuristic"

    @field_validator("comment_prefixes")
    @classmethod
    def _bound_comment_prefixes(cls, value: list[str]) -> list[str]:
        if len(value) > 8:
            raise ValueError("at most 8 comment prefixes")
        for prefix in value:
            if not prefix or len(prefix) > 4:
                raise ValueError(f"implausible comment prefix: {prefix!r}")
        return value

    @field_validator("traces")
    @classmethod
    def _bound_traces(cls, value: list[TraceSpec]) -> list[TraceSpec]:
        if len(value) > MAX_TRACES:
            raise ValueError(f"layout declares {len(value)} traces, max is {MAX_TRACES}")
        seen = {trace.index for trace in value}
        if len(seen) != len(value):
            raise ValueError("trace indexes must be unique")
        return value

    def trace(self, index: int) -> TraceSpec | None:
        """The declared trace at `index`, or None when this layout has none."""
        return next((t for t in self.traces if t.index == index), None)

    @property
    def default_trace_index(self) -> int:
        """The trace a caller gets when it does not ask for a specific one."""
        return self.traces[0].index if self.traces else 1


class PreviewPatch(BaseModel):
    """One sampled window of the numeric body, taken from somewhere other than
    the top of the file."""

    model_config = ConfigDict(extra="forbid")

    # "25%", "50%", "75%", "tail" — where in the body this window came from.
    label: str
    # Body-relative index of `rows[0]`, i.e. counted AFTER `header_rows`, so
    # it is directly comparable to the indexes in `PreviewGrid.rows`.
    start_row: int
    # Aligned to `PreviewGrid.columns_shown`, exactly like `PreviewGrid.rows`.
    rows: list[list[str]] = Field(default_factory=list)


class PreviewGrid(BaseModel):
    """A small, deterministic sample of a raw file's text body.

    This is what structure detection reasons over — both the heuristics and
    the LLM. Keeping it small is the point: it turns a 37k-token whole-file
    prompt into a ~2k-token one.
    """

    model_config = ConfigDict(extra="forbid")

    delimiter: str
    decimal_separator: Literal[".", ","] = "."
    total_lines: int
    column_count: int
    # Leading non-empty lines that are not numeric data — the vendor preamble.
    # Counted over the whole file, not just the sampled rows, so a 200-line
    # header does not hide the body.
    header_rows: int = 0
    # The last few of those preamble lines, which is where column names live.
    header_cells: list[list[str]] = Field(default_factory=list)
    # `rows[r][c]` — the first rows of the numeric BODY, i.e. after
    # `header_rows`. Row indexes are body-relative, matching how `FileLayout`
    # counts them, so an index quoted against this grid can be used directly.
    # Cell `c` is column `columns_shown[c]`, which is c itself unless the file
    # is too wide to print whole.
    rows: list[list[str]] = Field(default_factory=list)
    # Absolute column indexes present in `rows` and in every patch. Equal to
    # `range(column_count)` unless the file is wider than can be shown.
    columns_shown: list[int] = Field(default_factory=list)
    # Further windows sampled from deeper in the body — see `PreviewPatch`.
    # Empty for a body short enough that `rows` already covers it.
    patches: list[PreviewPatch] = Field(default_factory=list)
    # Fraction of sampled body rows whose cell in this column parses as a
    # number, per column. The single strongest structural signal available
    # without an LLM.
    numeric_fraction: list[float] = Field(default_factory=list)
    leading_comment_lines: int = 0
    body_lines: int = 0
    blank_separated_blocks: int = 0
    truncated_rows: bool = False
    truncated_columns: bool = False


class IngestionJobOut(BaseModel):
    """Response shape for GET /ingestion-jobs/{id}."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_file_id: uuid.UUID
    status: str
    parser_used: str | None = None
    parser_version: str | None = None
    parser_confidence: float | None = None
    canonicalization_version: str | None = None
    header_hash: str | None = None
    extracted_metadata_raw: dict[str, Any] | None = None
    sanity_check_flags: dict[str, Any] | None = None
    extracted_metadata_confirmed: dict[str, Any] | None = None
    file_layout: dict[str, Any] | None = None
    structure_preview: dict[str, Any] | None = None
    layout_source: str | None = None
    error_message: str | None = None
    attempt_count: int = 0
    max_attempts: int = 3
    run_after: datetime | None = None
    lease_expires_at: datetime | None = None
    draft_spectrum_id: uuid.UUID | None = None
    draft_dataset_id: uuid.UUID | None = None
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


class DeclareLayoutRequest(BaseModel):
    """Body for POST /ingestion-jobs/{id}/layout — the owner telling us how
    their file is laid out after automatic detection gave up. Verified against
    the file's bytes before it is accepted."""

    model_config = ConfigDict(extra="forbid")

    layout: FileLayout
