"""LLM-based metadata extraction fallback, used when no deterministic vendor
parser recognizes a raw file's header.

Security / cost boundary (every invariant here is asserted in code below and
covered by tests in ``tests/test_llm_fallback.py``):

* **The model only ever sees ``header_text[:MAX_HEADER_CHARS]`` (65536 chars,
  == ``jobs.HEADER_SNIFF_BYTES``) plus the bare filename.** It is never given
  whole-file content, a file path, an S3 key, SQL, or a shell string. The
  header is re-truncated here defensively even though the worker already
  sniffs only a leading chunk.
* **The model's output is only ever a typed ``ExtractedMetadata``.** The
  reply is a bare JSON object matching a JSON Schema (structured output, not
  free-text parsing) and *always* passes through
  ``ExtractedMetadata.model_validate(...)``. A schema-violating response
  raises ``LLMExtractionError`` and nothing is written to the database.
* **Deterministic decoding:** ``temperature`` is pinned to 0 and the reply is
  capped at ``MAX_OUTPUT_TOKENS`` so two identical headers give the same
  parse and a single call can never run away.
* **Cache key is FORMAT-ONLY.** The ``VendorParseCache`` row is keyed on
  ``compute_header_hash(header_text)`` — the normalized header template
  alone. The filename is deliberately *not* folded in, so a second upload of
  a different file that shares a header template is a pure cache hit with
  ZERO LLM calls. Filename-derived facts are layered on afterwards by the
  deterministic ``filename_overlay`` (also no LLM).
* **No key configured is not an error.** When no credential resolves
  the fallback returns ``ExtractedMetadata(modality="raman")`` plus the
  filename overlay instead of raising.
"""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion import filename_overlay
from app.ingestion.header_hash import compute_header_hash
from app.llm import LLMError, complete_json
from app.llm_credentials import LLMCredential, platform_credential
from app.models.enums import Modality, ParseSource
from app.models.vendor_parse_cache import VendorParseCache
from app.schemas.ingestion import ExtractedMetadata

# Must stay == app.ingestion.jobs.HEADER_SNIFF_BYTES. The worker already
# decodes only a leading chunk; this is a belt-and-braces cap so a future
# call site that hands us more text still cannot leak whole-file content to
# the model.
MAX_HEADER_CHARS = 65536

# Hard cap on the model's reply. ExtractedMetadata itself is tiny, but on a
# reasoning model the chain of thought is billed against this same budget
# (measured: 100-870 reasoning tokens for a metadata-rich header), so a cap
# sized for the answer alone truncates the JSON mid-string. 4096 leaves room
# for both while still bounding a misbehaving model.
MAX_OUTPUT_TOKENS = 4096

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
    "`raw_extra_fields` as flat string/number values only: at most 12 entries, "
    "keys at most 40 characters, values at most 120 characters, and nothing "
    "that is already covered by a named field above. Skip padding, debug, and "
    "aux parameters — do not transcribe the whole header.\n"
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
    header_text: str,
    db: Session,
    *,
    filename: str | None = None,
    credential: LLMCredential | None = None,
) -> tuple[ExtractedMetadata, str]:
    """Extract metadata from `header_text` via the shared LLM client, with a
    `VendorParseCache` lookup/write keyed by the FORMAT-ONLY header template
    hash (`compute_header_hash(header_text)`). The filename is never part of
    the cache key — two files that share a header template are a pure cache
    hit with zero LLM calls; filename facts are layered on deterministically
    afterwards by `filename_overlay.apply`.

    Returns `(metadata, source)` where `source` is:
      * "cache"        — served from `VendorParseCache`, no LLM call
      * "llm"          — fresh model call, result cached
      * "filename-only" — no LLM key configured; header ignored, filename
                          overlay applied to an empty `ExtractedMetadata`

    `credential` is the file owner's LLM credential (see
    `app.llm_credentials.resolve_for_user`); None falls back to the platform
    key. A result produced with the *user's own* key is deliberately not
    written to `VendorParseCache` — see below.
    """
    # Belt-and-braces: never hand the model more than the header sniff window,
    # regardless of what a caller passes.
    header_text = header_text[:MAX_HEADER_CHARS]
    name_hint = (filename or "").strip()
    header_hash = compute_header_hash(header_text)

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
        return filename_overlay.apply(metadata, name_hint), "cache"

    credential = credential or platform_credential()
    if credential is None:
        # No key: degrade gracefully rather than failing the ingestion job.
        # Return a valid empty Raman metadata object plus whatever the
        # filename deterministically tells us. Not cached — a real parse
        # should replace this once a key is configured.
        metadata = filename_overlay.apply(ExtractedMetadata(modality="raman"), name_hint)
        return metadata, "filename-only"

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
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.0,
            credential=credential,
        )
    except LLMError as exc:
        raise LLMExtractionError(f"LLM API call failed: {exc}") from exc

    try:
        metadata = ExtractedMetadata.model_validate(tool_input)
    except (ValidationError, TypeError) as exc:
        raise LLMExtractionError(f"LLM tool output failed schema validation: {exc}") from exc

    # `format_metadata` is the FORMAT-ONLY parse and is what gets cached, so a
    # later file with the same header template but a different name does not
    # inherit this file's filename-derived fields. The overlay is applied only
    # to the value returned to *this* caller.
    format_metadata = _guard_laser_wavelength(metadata)

    try:
        cache_modality = Modality(format_metadata.modality)
    except ValueError:
        cache_modality = Modality.raman

    if credential.is_user_supplied:
        # `VendorParseCache` is keyed on the header template alone and is read
        # by every user who later uploads that format. Writing a result that
        # came from *this* user's private model would serve their output to
        # strangers — and, unlike a layout, this template is never
        # independently verified, so a bad or adversarial answer would
        # propagate. They also asked for their data to stay on their own
        # provider; the derived template staying private follows from that.
        # The cache simply refills the next time a platform-key upload of the
        # same format comes through.
        return filename_overlay.apply(format_metadata, name_hint), "llm"

    cache_row = VendorParseCache(
        header_hash=header_hash,
        modality=cache_modality,
        vendor_format=None,
        parser_version=MODEL_ID,
        source=ParseSource.llm,
        parsed_template=format_metadata.model_dump(mode="json"),
        hit_count=0,
    )
    db.add(cache_row)
    db.commit()

    return filename_overlay.apply(format_metadata, name_hint), "llm"
