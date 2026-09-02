"""LLM-based metadata extraction fallback, used when no deterministic vendor
parser recognizes a raw file's header.

Security boundary: the model returns a bare JSON object matching a JSON
Schema (structured output, not free-text parsing) and then *always* passes
through `ExtractedMetadata.model_validate(...)`. LLM output never touches a
file path, SQL string, or shell command — it only ever populates typed
pydantic fields on `ExtractedMetadata`. A schema-violating response raises
`LLMExtractionError` and nothing is written to the database.
"""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.header_hash import compute_header_hash
from app.llm import LLMError, complete_json
from app.models.enums import Modality, ParseSource
from app.models.vendor_parse_cache import VendorParseCache
from app.schemas.ingestion import ExtractedMetadata

# Recorded on the cache row's `parser_version`; the concrete model slug is
# an operator env choice (OPENROUTER_INGESTION_MODEL / OPENROUTER_MODEL).
MODEL_ID = "openrouter-llm"

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
    "files from an unrecognized vendor format. You are given the file's name "
    "and its raw header text. Use BOTH: filenames often encode the sample, "
    "the excitation laser, or acquisition settings (e.g. "
    "'polystyrene_532nm_10s_x50.txt'). Return a JSON object with every field "
    "you can confidently determine. Leave a field null if it is not present "
    "or you are not confident — never guess. Put other useful facts in "
    "`raw_extra_fields` as flat string/number values only.\n"
    "\n"
    "CRITICAL — do not confuse two different quantities:\n"
    "- `laser_wavelength_nm` is the EXCITATION LASER wavelength, in "
    "nanometres. It is almost always one of 244, 257, 325, 442, 488, 514, "
    "532, 633, 660, 671, 785, 808, 830, 1064. Cues: 'laser', 'excitation', "
    "'Ex', 'nm'.\n"
    "- WAVENUMBER / Raman shift is the spectrum's x-axis, in cm^-1, spanning "
    "roughly 50-4000. Cues: 'cm-1', 'cm^-1', 'Raman shift', a range like "
    "'100-3200', or the first column of the numeric data.\n"
    "A wavenumber value, a spectral-range endpoint, a grating value (e.g. "
    "600, 1800 lines/mm), or a pixel count must NEVER be placed in "
    "`laser_wavelength_nm`. If you cannot clearly identify the laser "
    "wavelength, set `laser_wavelength_nm` to null. Only emit values between "
    "200 and 1100 there."
)

# Excitation-laser wavelengths are physically bounded; a value outside this
# window in `laser_wavelength_nm` is almost certainly a wavenumber, grating,
# or pixel count the model misfiled. Move it aside rather than store it.
_LASER_NM_MIN = 200.0
_LASER_NM_MAX = 1100.0


class LLMExtractionError(Exception):
    """Raised when the LLM response cannot be validated into ExtractedMetadata.
    Callers should treat this as a hard failure of the ingestion job — never
    write partial/invalid metadata to the database."""


def _guard_laser_wavelength(metadata: ExtractedMetadata) -> ExtractedMetadata:
    """Deterministic backstop for the classic wavenumber/wavelength mix-up: if
    the model put an implausible value in `laser_wavelength_nm`, null it and
    stash the original in `raw_extra_fields` for human review rather than
    letting a Raman shift masquerade as an excitation wavelength."""
    nm = metadata.laser_wavelength_nm
    if nm is not None and not (_LASER_NM_MIN <= nm <= _LASER_NM_MAX):
        extra = dict(metadata.raw_extra_fields)
        extra.setdefault("llm_flagged_laser_wavelength_nm", nm)
        return metadata.model_copy(update={"laser_wavelength_nm": None, "raw_extra_fields": extra})
    return metadata


async def extract_metadata_via_llm(
    header_text: str, db: Session, *, filename: str | None = None
) -> tuple[ExtractedMetadata, str]:
    """Extract metadata from `header_text` (and `filename`, if given) via the
    shared LLM client, with a `VendorParseCache` lookup/write keyed by the
    header template hash — the filename is folded in so two files with an
    identical header but different names don't share a cache entry.

    Returns `(metadata, source)` where `source` is "cache" on a cache hit or
    "llm" after a fresh model call.
    """
    name_hint = (filename or "").strip()
    header_hash = compute_header_hash(f"{name_hint}\n{header_text}")

    cached = (
        db.query(VendorParseCache).filter(VendorParseCache.header_hash == header_hash).one_or_none()
    )
    if cached is not None:
        try:
            metadata = ExtractedMetadata.model_validate(cached.parsed_template)
        except ValidationError as exc:
            raise LLMExtractionError(f"Cached parse template failed validation: {exc}") from exc
        cached.hit_count = (cached.hit_count or 0) + 1
        db.add(cached)
        db.commit()
        return metadata, "cache"

    user_prompt = (
        f"Filename: {name_hint}\n\nRaw header text:\n\n{header_text}"
        if name_hint
        else f"Raw header text:\n\n{header_text}"
    )
    try:
        tool_input = await complete_json(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            schema=_TOOL_INPUT_SCHEMA,
            model=settings.OPENROUTER_INGESTION_MODEL or None,
            max_tokens=1024,
        )
    except LLMError as exc:
        raise LLMExtractionError(f"LLM API call failed: {exc}") from exc

    try:
        metadata = ExtractedMetadata.model_validate(tool_input)
    except (ValidationError, TypeError) as exc:
        raise LLMExtractionError(f"LLM tool output failed schema validation: {exc}") from exc

    metadata = _guard_laser_wavelength(metadata)

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
