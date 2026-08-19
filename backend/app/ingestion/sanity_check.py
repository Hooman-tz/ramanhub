"""Pure-function sanity checking of extracted metadata against the
`MetadataFieldDefinition` registry for a modality.

Flags, never rejects: a value outside the expected range/allowed-values
list is a candidate for human review, not an error — e.g. a genuinely
custom laser wavelength is real data, not a bug.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.field_registry import MetadataFieldDefinition
from app.schemas.ingestion import ExtractedMetadata


def check(metadata: ExtractedMetadata, modality: str, db: Session) -> dict[str, str]:
    """Return `{field_key: reason}` for every field that looks off:
    - required fields that are None/missing
    - numeric fields outside [min_value, max_value]
    - fields with `allowed_values` set where the value isn't in that list
    """
    flags: dict[str, str] = {}

    definitions = (
        db.query(MetadataFieldDefinition)
        .filter(MetadataFieldDefinition.modality == modality)
        .all()
    )

    values = metadata.model_dump()

    for definition in definitions:
        field_key = definition.field_key
        value = values.get(field_key)

        if value is None:
            if definition.required:
                flags[field_key] = "required field is missing"
            continue

        has_range = definition.min_value is not None or definition.max_value is not None
        if has_range and isinstance(value, (int, float)):
            min_v = definition.min_value
            max_v = definition.max_value
            if min_v is not None and value < float(min_v):
                flags[field_key] = f"value {value} is below minimum {min_v}"
            elif max_v is not None and value > float(max_v):
                flags[field_key] = f"value {value} is above maximum {max_v}"

        if definition.allowed_values and value not in definition.allowed_values:
            flags[field_key] = (
                f"value {value!r} is not in the allowed set {definition.allowed_values} "
                "(flagged for review, not rejected)"
            )

    return flags
