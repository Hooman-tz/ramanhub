"""Collapse three duplicated uniqueness declarations into one unique index each

Revision ID: e7a4c1b60d93
Revises: c3f7a2b9d4e1
Create Date: 2026-09-04

Three columns are declared `unique=True, index=True` on the model
(`analysis_datasets.accession`, `reference_entries.spectrum_id`,
`spectrum_peaks.spectrum_id`). SQLAlchemy renders that as a *single* unique
index named `ix_<table>_<column>`. The migrations that created these tables
instead wrote a unique constraint *and* a separate non-unique index, so every
one of those columns carries two indexes where one would do, and CI's
model/migration drift check has been failing on all three.

This aligns the database with the models: drop the constraint and the plain
index, create the unique index the models actually describe. Uniqueness is
preserved throughout in the sense that matters — a unique index enforces
exactly what the constraint did; Postgres implements unique constraints as
unique indexes underneath.
"""

from __future__ import annotations

from alembic import op

revision = "e7a4c1b60d93"
down_revision = "c3f7a2b9d4e1"
branch_labels = None
depends_on = None


# (table, column, constraint name, index name)
_TARGETS = (
    ("analysis_datasets", "accession", "uq_analysis_dataset_accession", "ix_analysis_datasets_accession"),
    ("reference_entries", "spectrum_id", "reference_entries_spectrum_id_key", "ix_reference_entries_spectrum_id"),
    ("spectrum_peaks", "spectrum_id", "spectrum_peaks_spectrum_id_key", "ix_spectrum_peaks_spectrum_id"),
)


def upgrade() -> None:
    for table, column, constraint, index in _TARGETS:
        # `IF EXISTS` because these tables were created across several
        # revisions and a database restored from an older dump may be missing
        # one of the two halves. Dropping the constraint takes its implicit
        # index with it.
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{constraint}"')
        op.execute(f'DROP INDEX IF EXISTS "{index}"')
        op.execute(f'CREATE UNIQUE INDEX "{index}" ON {table} ({column})')


def downgrade() -> None:
    for table, column, constraint, index in _TARGETS:
        op.execute(f'DROP INDEX IF EXISTS "{index}"')
        op.execute(
            f'ALTER TABLE {table} ADD CONSTRAINT "{constraint}" UNIQUE ({column})'
        )
        op.execute(f'CREATE INDEX "{index}" ON {table} ({column})')
