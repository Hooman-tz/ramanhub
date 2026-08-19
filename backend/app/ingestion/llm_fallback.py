"""LLM-based metadata extraction fallback, used when no deterministic vendor
parser recognizes a raw file's header.

Security boundary: the Anthropic response is coerced into a tool call
(structured output via tool-use forcing, not free-text parsing) and then
*always* passed through `ExtractedMetadata.model_validate(...)`. LLM output
never touches a file path, SQL string, or shell command — it only ever
populates typed pydantic fields on `ExtractedMetadata`. A schema-violating
response raises `LLMExtractionError` and nothing is written to the
database.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.header_hash import compute_header_hash
from app.models.enums import Modality, ParseSource
from app.models.vendor_parse_cache import VendorParseCache
from app.schemas.ingestion import ExtractedMetadata

MODEL_ID = "claude-sonnet-5"

_TOOL_NAME = "extract_raman_metadata"

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


def _extract_tool_input(message: Any) -> dict:
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
            return block.input
    raise LLMExtractionError("Model did not return the expected tool call")


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

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        message = await client.messages.create(
            model=MODEL_ID,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[
                {
                    "name": _TOOL_NAME,
                    "description": "Record extracted Raman instrument metadata.",
                    "input_schema": _TOOL_INPUT_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[
                {
                    "role": "user",
                    "content": f"Raw header text:\n\n{header_text}",
                }
            ],
        )
    except anthropic.APIError as exc:
        raise LLMExtractionError(f"Anthropic API call failed: {exc}") from exc

    tool_input = _extract_tool_input(message)

    try:
        # tool_input may arrive as a dict already; guard against a stray
        # JSON-string edge case from some SDK/response shapes.
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
        parser_version=MODEL_ID,
        source=ParseSource.llm,
        parsed_template=metadata.model_dump(mode="json"),
        hit_count=0,
    )
    db.add(cache_row)
    db.commit()

    return metadata, "llm"
