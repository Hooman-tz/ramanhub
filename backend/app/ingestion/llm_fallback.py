"""LLM-based metadata extraction fallback, used when no deterministic vendor
parser recognizes a raw file's header.

Security boundary — unchanged by the provider seam, and the thing to be
careful about when editing this file: the model response is coerced into a
tool call (structured output via tool-use forcing, not free-text parsing) and
then *always* passed through `ExtractedMetadata.model_validate(...)`. LLM
output never touches a file path, SQL string, or shell command — it only ever
populates typed pydantic fields on `ExtractedMetadata`. A schema-violating
response raises `LLMExtractionError` and nothing is written to the database.

`app.ingestion.llm_providers` deliberately returns an unvalidated `dict`, so
this module remains the only place that decides what may reach the database.
The `validate=` callback handed to the provider is for its corrective retry
only — it is not a substitute for the validation below.

Which provider runs (Anthropic direct, or OpenRouter with open-weights
models) is a config question; see `app.config` and `llm_providers`.
"""
from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ingestion.header_hash import compute_header_hash
from app.ingestion.llm_providers import LLMProviderError, resolve_provider
from app.models.enums import Modality, ParseSource
from app.models.vendor_parse_cache import VendorParseCache
from app.schemas.ingestion import ExtractedMetadata

_TOOL_NAME = "extract_raman_metadata"
_TOOL_DESCRIPTION = "Record extracted Raman instrument metadata."

_TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "modality": {"type": "string", "default": "raman"},
        "instrument_vendor": {"type": ["string", "null"]},
        "instrument_model": {"type": ["string", "null"]},
        "laser_wavelength_nm": {"type": ["number", "null"]},
        "laser_power_mw": {"type": ["number", "null"]},
        "integration_time_ms": {"type": ["number", "null"]},
        "accumulations": {"type": ["integer", "null"]},
        "spectral_range_cm1": {
            "type": ["string", "null"],
            "description": "Formatted as 'min-max', e.g. '100-3200'.",
        },
        "resolution_cm1": {"type": ["number", "null"]},
        "acquisition_datetime": {"type": ["string", "null"]},
        "sample_description": {"type": ["string", "null"]},
        "grating_lines_mm": {"type": ["number", "null"]},
        "objective_magnification": {"type": ["number", "null"]},
        "raw_extra_fields": {
            "type": "object",
            "description": (
                "Any other useful facts found in the header that don't map to a "
                "known field above. Flat key -> string/number values only. "
                "No nested objects or arrays."
            ),
            "additionalProperties": {"type": ["string", "number"]},
        },
    },
    "required": ["modality"],
}

_SYSTEM_PROMPT = (
    "You extract structured instrument metadata from raw Raman spectroscopy "
    "file headers. You will be given the raw header text of a spectral data "
    "file from an unrecognized vendor format. Call the "
    f"`{_TOOL_NAME}` tool exactly once with every field you can confidently "
    "determine from the header. Leave a field null if it is not present or "
    "you are not confident about it — never guess. Put any other useful "
    "facts you find in `raw_extra_fields` as flat string/number values only."
)


class LLMExtractionError(Exception):
    """Raised when the LLM response cannot be validated into ExtractedMetadata.
    Callers should treat this as a hard failure of the ingestion job — never
    write partial/invalid metadata to the database."""


async def extract_metadata_via_llm(
    header_text: str, db: Session
) -> tuple[ExtractedMetadata, str]:
    """Extract metadata from `header_text` via the Anthropic API, with a
    `VendorParseCache` lookup/write keyed by the header's template hash.

    Returns `(metadata, source)` where `source` is "cache" on a cache hit or
    "llm" after a fresh model call.
    """
    header_hash = compute_header_hash(header_text)

    cached = (
        db.query(VendorParseCache)
        .filter(VendorParseCache.header_hash == header_hash)
        .one_or_none()
    )
    if cached is not None:
        try:
            metadata = ExtractedMetadata.model_validate(cached.parsed_template)
        except ValidationError as exc:
            raise LLMExtractionError(
                f"Cached parse template failed validation: {exc}"
            ) from exc
        cached.hit_count = (cached.hit_count or 0) + 1
        db.add(cached)
        db.commit()
        return metadata, "cache"

    provider = resolve_provider()

    # Only the header is sent, never the spectrum body — see
    # `app.ingestion.jobs._extract_header_text`, which truncates at the first
    # numeric data row. Sending the whole file costs ~100x the tokens and
    # makes extraction *worse*, because nine useful lines end up buried in
    # a thousand rows of numbers.
    prompt = f"Raw header text:\n\n{header_text}"

    try:
        tool_input = await provider.call_tool(
            system=_SYSTEM_PROMPT,
            user_text=prompt,
            tool_name=_TOOL_NAME,
            tool_description=_TOOL_DESCRIPTION,
            tool_schema=_TOOL_INPUT_SCHEMA,
            # Lets the provider retry once with the schema error fed back.
            # This is a quality aid for small models, NOT the security
            # boundary — the authoritative validation is below and runs
            # regardless of what happened in here.
            validate=lambda payload: ExtractedMetadata.model_validate(payload),
        )
    except LLMProviderError as exc:
        raise LLMExtractionError(str(exc)) from exc

    try:
        if isinstance(tool_input, str):
            tool_input = json.loads(tool_input)
        metadata = ExtractedMetadata.model_validate(tool_input)
    except (ValidationError, json.JSONDecodeError, TypeError) as exc:
        raise LLMExtractionError(f"LLM tool output failed schema validation: {exc}") from exc

    try:
        cache_modality = Modality(metadata.modality)
    except ValueError:
        cache_modality = Modality.raman

    cache_row = VendorParseCache(
        header_hash=header_hash,
        modality=cache_modality,
        vendor_format=None,
        parser_version=provider.model_id,
        source=ParseSource.llm,
        parsed_template=metadata.model_dump(mode="json"),
        hit_count=0,
    )
    db.add(cache_row)
    db.commit()

    return metadata, "llm"
