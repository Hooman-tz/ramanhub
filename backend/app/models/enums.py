"""Shared Python enums, mirrored as native Postgres ENUM types.

Namespaced by modality per the architecture doc: Raman is the only modality
implemented in v1, but the schema (and these enums) are structured so mass
spec / NMR can be added later without a rewrite.

Each Python enum below has a matching `sqlalchemy.Enum` instance (native
Postgres ENUM type, `native_enum=True`). Model modules must import and reuse
these shared instances (rather than constructing their own `Enum(...)`) so
SQLAlchemy/Alembic treat every column of a given kind as the same Postgres
type instead of creating a duplicate type per table.
"""
import enum

from sqlalchemy import Enum as PgEnum


class Modality(str, enum.Enum):
    raman = "raman"
    mass_spec = "mass_spec"
    nmr = "nmr"


class UploadStatus(str, enum.Enum):
    uploaded = "uploaded"
    parsing = "parsing"
    parsed = "parsed"
    failed = "failed"


class IngestionStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ParseSource(str, enum.Enum):
    deterministic = "deterministic"
    llm = "llm"


class SpectrumState(str, enum.Enum):
    draft = "draft"
    published = "published"
    embargoed = "embargoed"


class FieldDataType(str, enum.Enum):
    number = "number"
    string = "string"
    enum = "enum"
    boolean = "boolean"
    date = "date"


def _values_callable(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


modality_enum = PgEnum(
    Modality, name="modality", native_enum=True, values_callable=_values_callable
)
upload_status_enum = PgEnum(
    UploadStatus, name="upload_status", native_enum=True, values_callable=_values_callable
)
ingestion_status_enum = PgEnum(
    IngestionStatus, name="ingestion_status", native_enum=True, values_callable=_values_callable
)
parse_source_enum = PgEnum(
    ParseSource, name="parse_source", native_enum=True, values_callable=_values_callable
)
spectrum_state_enum = PgEnum(
    SpectrumState, name="spectrum_state", native_enum=True, values_callable=_values_callable
)
field_data_type_enum = PgEnum(
    FieldDataType, name="field_data_type", native_enum=True, values_callable=_values_callable
)
