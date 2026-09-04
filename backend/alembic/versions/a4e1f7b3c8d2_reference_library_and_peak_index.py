"""The public reference library, and the peak index that makes matching cheap.

Two tables:

`reference_entries` — catalogue metadata that turns an ordinary published
spectrum into an identity claim (compound name, formula, provenance, trust
tier). References are deliberately *not* a separate kind of spectrum: bundled
RRUFF imports and user contributions both point at a normal `spectra` row, so
they share one ingestion, storage and similarity-indexing path.

`spectrum_peaks` — detected bands per spectrum revision. The load-bearing
column is `binned_cm1`: peak positions quantized to 4 cm-1 buckets, GIN
indexed, so "which library spectra have a band near 1085?" is one index scan
instead of a full-corpus read. Without it, cosine matching is linear in corpus
size and an 8.5k-spectrum library makes every match request slow.

`source` is `varchar`, not a `PgEnum`, for the reason spelled out in
b6d3e0f2a915: the set of sources will grow (rruff -> user -> curated -> ...)
and extending a Postgres enum costs a migration every time. `trust_tier` and
`curation_status` are closed sets and do get real enums.

Note on size: these two tables add roughly 1.6 KB per spectrum (~17 MB across
the planned 8.5k-entry RRUFF seed). The larger cost of that seed is the
*existing* `similarity_features.vector`, ~7 KB/row of JSONB, or ~85 MB.
Shrinking that to float32 bytea is a worthwhile follow-up and deliberately not
attempted here.

Revision ID: a4e1f7b3c8d2
Revises: b6d3e0f2a915
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a4e1f7b3c8d2"
down_revision: str | Sequence[str] | None = "b6d3e0f2a915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


trust_tier_enum = postgresql.ENUM(
    "curated", "community", name="reference_trust_tier", create_type=False
)
curation_status_enum = postgresql.ENUM(
    "approved", "demoted", "removed", name="reference_curation_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    trust_tier_enum.create(bind, checkfirst=True)
    curation_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "reference_entries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "spectrum_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spectra.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("compound_name", sa.String(200), nullable=False),
        sa.Column(
            "common_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("chemical_formula", sa.String(120), nullable=True),
        sa.Column("cas_number", sa.String(20), nullable=True),
        sa.Column("mineral_name", sa.String(120), nullable=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=True),
        sa.Column("source_dataset", sa.String(80), nullable=True),
        sa.Column("provenance_url", sa.Text(), nullable=True),
        sa.Column("trust_tier", trust_tier_enum, nullable=False),
        sa.Column(
            "curation_status",
            curation_status_enum,
            nullable=False,
            server_default=sa.text("'approved'"),
        ),
        sa.Column(
            "flagged_for_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "contributed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "curated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("curated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # Nullable `source_id` is load-bearing: Postgres treats NULLs as
        # distinct, so user submissions (no upstream id) are unconstrained
        # while a re-run of the RRUFF import collides on every row it already
        # created — free idempotency for the seeder.
        sa.UniqueConstraint("source", "source_id", name="uq_reference_source_id"),
    )
    op.create_index("ix_reference_entries_spectrum_id", "reference_entries", ["spectrum_id"])
    op.create_index("ix_reference_entries_compound_name", "reference_entries", ["compound_name"])
    op.create_index("ix_reference_entries_chemical_formula", "reference_entries", ["chemical_formula"])
    op.create_index("ix_reference_entries_cas_number", "reference_entries", ["cas_number"])
    op.create_index("ix_reference_entries_trust_tier", "reference_entries", ["trust_tier"])
    op.create_index("ix_reference_entries_curation_status", "reference_entries", ["curation_status"])
    op.create_index("ix_reference_entries_flagged_for_review", "reference_entries", ["flagged_for_review"])
    op.create_index("ix_reference_entries_source", "reference_entries", ["source", "source_dataset"])

    op.create_table(
        "spectrum_peaks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "spectrum_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spectra.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "modality",
            postgresql.ENUM("raman", "mass_spec", "nmr", name="modality", create_type=False),
            nullable=False,
        ),
        sa.Column("peak_index_version", sa.String(40), nullable=False),
        sa.Column("canonicalization_version", sa.String(40), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("primary_peak_cm1", sa.Float(), nullable=True),
        sa.Column("primary_peak_prominence", sa.Float(), nullable=True),
        sa.Column("peak_to_background", sa.Float(), nullable=True),
        sa.Column("peak_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("wavenumber_min", sa.Float(), nullable=False),
        sa.Column("wavenumber_max", sa.Float(), nullable=False),
        sa.Column("baseline_level", sa.Float(), nullable=True),
        sa.Column("noise_sigma", sa.Float(), nullable=True),
        sa.Column(
            "peaks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "binned_cm1",
            postgresql.ARRAY(sa.Integer()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "qc_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "qc_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_spectrum_peaks_spectrum_id", "spectrum_peaks", ["spectrum_id"])
    op.create_index("ix_spectrum_peaks_primary_peak_cm1", "spectrum_peaks", ["primary_peak_cm1"])
    op.create_index("ix_spectrum_peaks_peak_to_background", "spectrum_peaks", ["peak_to_background"])
    # The whole point of the table. Also declared in the model's
    # `__table_args__`, because the test harness builds its schema with
    # `Base.metadata.create_all()` and would otherwise run without it.
    op.create_index(
        "ix_spectrum_peaks_bins_gin",
        "spectrum_peaks",
        ["binned_cm1"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_spectrum_peaks_bins_gin", table_name="spectrum_peaks")
    op.drop_index("ix_spectrum_peaks_peak_to_background", table_name="spectrum_peaks")
    op.drop_index("ix_spectrum_peaks_primary_peak_cm1", table_name="spectrum_peaks")
    op.drop_index("ix_spectrum_peaks_spectrum_id", table_name="spectrum_peaks")
    op.drop_table("spectrum_peaks")

    for name in (
        "ix_reference_entries_source",
        "ix_reference_entries_flagged_for_review",
        "ix_reference_entries_curation_status",
        "ix_reference_entries_trust_tier",
        "ix_reference_entries_cas_number",
        "ix_reference_entries_chemical_formula",
        "ix_reference_entries_compound_name",
        "ix_reference_entries_spectrum_id",
    ):
        op.drop_index(name, table_name="reference_entries")
    op.drop_table("reference_entries")

    bind = op.get_bind()
    curation_status_enum.drop(bind, checkfirst=True)
    trust_tier_enum.drop(bind, checkfirst=True)
