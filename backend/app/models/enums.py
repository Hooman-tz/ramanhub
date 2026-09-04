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
    # Parsed fine, but the file's structure could not be worked out and the
    # owner has to declare it. A question, not a failure: the upload is intact
    # and resumes the moment the layout arrives.
    needs_input = "needs_input"


class ParseSource(str, enum.Enum):
    deterministic = "deterministic"
    llm = "llm"


class SpectrumState(str, enum.Enum):
    draft = "draft"
    published = "published"
    embargoed = "embargoed"


class FindingState(str, enum.Enum):
    """Findings reuse the draft/published split but deliberately NOT
    `SpectrumState`'s third member.

    An embargo is a property of *data* — "this measurement is private until
    the paper lands". A Finding is a write-up about data that is already
    under its own embargo; giving it a second, independent embargo clock
    would create a state where the narrative is public and the spectra it
    discusses are not. Publishing a Finding requires its member spectra to
    be published, which is the simpler and stricter rule.
    """

    draft = "draft"
    published = "published"


class DatasetState(str, enum.Enum):
    """Datasets reuse the Finding draft/published split, not `SpectrumState`.

    A dataset is a *selection* of spectra, and each member carries its own
    embargo clock. Giving the container a second, independent clock would
    let a published dataset point at spectra that are still private — so
    publishing a dataset instead requires every member to be published
    already, the same stricter rule Findings use.
    """

    draft = "draft"
    published = "published"


class FindingEntryKind(str, enum.Enum):
    """What one post in a Finding thread contains.

    This is the "add results step by step" axis: a thread grows by
    appending entries, so a follow-up analysis is a new entry rather than
    an edit that silently rewrites what readers already saw.

    Analysis entries store their PARAMETERS in `config`, not a rendered
    image, so the figure is recomputed from the live data and stays
    reproducible.
    """

    note = "note"
    figure = "figure"
    spectra = "spectra"
    peaks = "peaks"
    pca = "pca"
    hca = "hca"
    attachment = "attachment"


class FieldDataType(str, enum.Enum):
    number = "number"
    string = "string"
    enum = "enum"
    boolean = "boolean"
    date = "date"


class ReferenceTrustTier(str, enum.Enum):
    """How much a reference entry's identity claim has been vetted.

    `curated` is bundled or staff-vetted reference data (RRUFF and friends).
    `community` is user-contributed: auto-approved and immediately matchable,
    but ranked below a curated entry at equal similarity so an unvetted
    submission cannot silently displace a known-good standard.
    """

    curated = "curated"
    community = "community"


class ReferenceCurationStatus(str, enum.Enum):
    """Moderation state of a reference entry.

    Not a publication gate — entries land `approved` and are matchable at
    once. This exists so a reference later found to be mislabelled can be
    demoted out of the curated tier or removed from matching entirely.
    """

    approved = "approved"
    demoted = "demoted"
    removed = "removed"


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
finding_state_enum = PgEnum(
    FindingState, name="finding_state", native_enum=True, values_callable=_values_callable
)
dataset_state_enum = PgEnum(
    DatasetState, name="dataset_state", native_enum=True, values_callable=_values_callable
)
finding_entry_kind_enum = PgEnum(
    FindingEntryKind,
    name="finding_entry_kind",
    native_enum=True,
    values_callable=_values_callable,
)
reference_trust_tier_enum = PgEnum(
    ReferenceTrustTier,
    name="reference_trust_tier",
    native_enum=True,
    values_callable=_values_callable,
)
reference_curation_status_enum = PgEnum(
    ReferenceCurationStatus,
    name="reference_curation_status",
    native_enum=True,
    values_callable=_values_callable,
)
