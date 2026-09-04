"""Let one raw file hold many spectra, and remember how files are laid out.

A Raman export routinely carries more than one spectrum — a column per sample,
a row per sample, or stacked two-column blocks. The pipeline previously assumed
"column 0 is wavenumber, column 1 is intensity", so those files imported as a
single spectrum (or as nonsense), and the schema enforced that assumption with
a unique constraint on `spectra.raw_file_id`.

This revision:

- replaces that unique constraint with `unique(raw_file_id, source_trace_index)`
  so each trace of a file is its own spectrum. Existing rows keep
  `source_trace_index IS NULL`, which stays unique per file under Postgres NULL
  semantics, so nothing already stored changes meaning;
- drops the unique constraint on `ingestion_jobs.draft_spectrum_id` (a job now
  creates several drafts; that column keeps pointing at the first) and adds
  `draft_dataset_id` for the dataset the drafts are grouped into;
- stores the detected `FileLayout`, the `PreviewGrid` behind it, and which rung
  of the detection ladder answered, on the job;
- adds `file_layout_cache`, so a format — including one a user declared by hand
  — is only worked out once;
- adds the `needs_input` ingestion status, for a file whose structure nobody
  could work out and whose owner needs to say what it is.

Note for operators: `vendor_parse_cache` rows written before this deploy stop
being reachable, because `compute_header_hash` now hashes the header template
only rather than the header plus every data row (which is why it never hit).
The table is a cache; it refills on the next upload of each format.

Revision ID: c7a4d2e8f019
Revises: e2b8c5a71d43
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c7a4d2e8f019"
down_revision: str | Sequence[str] | None = "e2b8c5a71d43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres will not accept a new enum label and a use of it in the same
    # transaction, but nothing here uses `needs_input` at migration time.
    op.execute("ALTER TYPE ingestion_status ADD VALUE IF NOT EXISTS 'needs_input'")

    op.add_column("spectra", sa.Column("source_trace_index", sa.Integer(), nullable=True))
    op.add_column("spectra", sa.Column("source_trace_label", sa.String(), nullable=True))
    op.drop_constraint("uq_spectra_raw_file_id", "spectra", type_="unique")
    op.create_index("ix_spectra_raw_file_id", "spectra", ["raw_file_id"])
    op.create_unique_constraint(
        "uq_spectrum_raw_file_trace", "spectra", ["raw_file_id", "source_trace_index"]
    )

    op.add_column("ingestion_jobs", sa.Column("file_layout", postgresql.JSONB(), nullable=True))
    op.add_column(
        "ingestion_jobs", sa.Column("structure_preview", postgresql.JSONB(), nullable=True)
    )
    op.add_column("ingestion_jobs", sa.Column("layout_source", sa.String(), nullable=True))
    op.add_column(
        "ingestion_jobs",
        sa.Column("draft_dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ingestion_job_draft_dataset",
        "ingestion_jobs",
        "analysis_datasets",
        ["draft_dataset_id"],
        ["id"],
    )
    op.create_index("ix_ingestion_jobs_draft_dataset_id", "ingestion_jobs", ["draft_dataset_id"])
    op.drop_constraint("uq_ingestion_jobs_draft_spectrum_id", "ingestion_jobs", type_="unique")
    op.create_index("ix_ingestion_jobs_draft_spectrum_id", "ingestion_jobs", ["draft_spectrum_id"])

    op.create_table(
        "file_layout_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("structure_hash", sa.String(), nullable=False),
        sa.Column("layout", postgresql.JSONB(), nullable=False),
        sa.Column("detector_version", sa.String(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_layout_cache_structure_hash",
        "file_layout_cache",
        ["structure_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_file_layout_cache_structure_hash", table_name="file_layout_cache")
    op.drop_table("file_layout_cache")

    op.drop_index("ix_ingestion_jobs_draft_spectrum_id", table_name="ingestion_jobs")
    op.create_unique_constraint(
        "uq_ingestion_jobs_draft_spectrum_id", "ingestion_jobs", ["draft_spectrum_id"]
    )
    op.drop_index("ix_ingestion_jobs_draft_dataset_id", table_name="ingestion_jobs")
    op.drop_constraint("fk_ingestion_job_draft_dataset", "ingestion_jobs", type_="foreignkey")
    op.drop_column("ingestion_jobs", "draft_dataset_id")
    op.drop_column("ingestion_jobs", "layout_source")
    op.drop_column("ingestion_jobs", "structure_preview")
    op.drop_column("ingestion_jobs", "file_layout")

    # Reversing the one-spectrum-per-file rule can only work if no file has
    # produced more than one spectrum since the upgrade; fail loudly rather
    # than silently dropping a scientist's data to satisfy the constraint.
    op.drop_constraint("uq_spectrum_raw_file_trace", "spectra", type_="unique")
    op.drop_index("ix_spectra_raw_file_id", table_name="spectra")
    op.create_unique_constraint("uq_spectra_raw_file_id", "spectra", ["raw_file_id"])
    op.drop_column("spectra", "source_trace_label")
    op.drop_column("spectra", "source_trace_index")

    # `needs_input` is left in the enum: removing a label requires rewriting
    # the type, and an unused label is harmless.
