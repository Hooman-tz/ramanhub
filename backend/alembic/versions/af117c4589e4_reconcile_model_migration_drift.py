"""Reconcile model/migration drift so `alembic check` is clean.

CI has asserted a single Alembic head and run `alembic check` since M5, but
those steps sit *after* `pytest` in the job and the suite had been failing at
an earlier step — so this drift had never actually been reported. It is all
pre-existing: the models and the migrations described the same tables slightly
differently.

Three kinds of difference, none of which change application behaviour:

1. `analysis_dataset_spectra` was missing the `(dataset_id, spectrum_id)`
   unique constraint its model has always declared. This is the only genuine
   missing guarantee here — duplicates were possible.
2. Five `created_at`/`updated_at` columns were nullable in the database while
   the models type them non-optional. Every one has a `now()` server default,
   so no code path writes NULL; the columns are backfilled defensively before
   the NOT NULL is applied.
3. Uniqueness on `users.orcid_id`, `users.profile_handle`, `publications.doi`
   and `similarity_features.spectrum_id` was created as a raw
   `CREATE UNIQUE INDEX` but declared as `unique=True` on the model column.
   Postgres enforces both identically, and UNIQUE constraints still treat
   NULLs as distinct, so replacing the partial `WHERE orcid_id IS NOT NULL`
   index with a plain UNIQUE constraint keeps "many users without an ORCID"
   legal. Constraints are created with Postgres's own default names
   (`<table>_<column>_key`) because that is what autogenerate expects from an
   unnamed model-level `unique=True`.

Revision ID: af117c4589e4
Revises: d1c4b7e2f9a0
Create Date: 2026-09-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "af117c4589e4"
down_revision: str | Sequence[str] | None = "d1c4b7e2f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) pairs that gain NOT NULL.
_TIMESTAMP_NOT_NULL = [
    ("analysis_datasets", "created_at"),
    ("analysis_datasets", "updated_at"),
    ("analysis_runs", "created_at"),
    ("similarity_features", "created_at"),
    ("similarity_features", "updated_at"),
]


def upgrade() -> None:
    # 1. `analysis_dataset_spectra`: a raw unique INDEX exists under the name
    #    the model uses for a UniqueConstraint. Same guarantee, different
    #    object — swap it so autogenerate sees what the model declares.
    op.execute(
        """
        DELETE FROM analysis_dataset_spectra a
        USING analysis_dataset_spectra b
        WHERE a.ctid < b.ctid
          AND a.dataset_id = b.dataset_id
          AND a.spectrum_id = b.spectrum_id
        """
    )
    # Defensive about which object shape this database happens to have: the
    # name exists as a bare unique index on some, and as a constraint (with its
    # own backing index of the same name) on others. Drop whichever is present,
    # then create the constraint the model declares.
    op.execute(
        "ALTER TABLE analysis_dataset_spectra "
        "DROP CONSTRAINT IF EXISTS uq_analysis_dataset_spectrum"
    )
    op.execute("DROP INDEX IF EXISTS uq_analysis_dataset_spectrum")
    op.execute(
        "ALTER TABLE analysis_dataset_spectra "
        "ADD CONSTRAINT uq_analysis_dataset_spectrum UNIQUE (dataset_id, spectrum_id)"
    )

    # 2. Timestamps: backfill any legacy NULLs, then tighten to NOT NULL.
    for table, column in _TIMESTAMP_NOT_NULL:
        op.execute(f"UPDATE {table} SET {column} = now() WHERE {column} IS NULL")
        op.alter_column(
            table,
            column,
            existing_type=postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            existing_server_default=sa.text("now()"),
        )

    # 3. `publications.doi` and `similarity_features.spectrum_id` each carry a
    #    UNIQUE constraint *and* a separate non-unique index. The models spell
    #    this as one `unique=True, index=True` column, i.e. a single unique
    #    index — collapse the pair into that.
    op.execute("ALTER TABLE publications DROP CONSTRAINT IF EXISTS publications_doi_key")
    op.execute("DROP INDEX IF EXISTS ix_publications_doi")
    op.create_index("ix_publications_doi", "publications", ["doi"], unique=True)

    op.execute(
        "ALTER TABLE similarity_features "
        "DROP CONSTRAINT IF EXISTS similarity_features_spectrum_id_key"
    )
    op.execute("DROP INDEX IF EXISTS ix_similarity_features_spectrum_id")
    op.create_index(
        "ix_similarity_features_spectrum_id",
        "similarity_features",
        ["spectrum_id"],
        unique=True,
    )

    # 4. `users`: raw unique indexes -> UNIQUE constraints under Postgres'
    #    default names, which is what an unnamed model-level `unique=True`
    #    produces. Dropping the partial WHERE on orcid_id is safe: a UNIQUE
    #    constraint still treats NULLs as distinct, so users without an ORCID
    #    remain unconstrained.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_orcid_id")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_profile_handle")
    op.execute("DROP INDEX IF EXISTS uq_users_orcid_id")
    op.execute("DROP INDEX IF EXISTS uq_users_profile_handle")
    op.execute("ALTER TABLE users ADD CONSTRAINT users_orcid_id_key UNIQUE (orcid_id)")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_profile_handle_key UNIQUE (profile_handle)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_profile_handle_key")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_orcid_id_key")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_profile_handle ON users (profile_handle)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_orcid_id "
        "ON users (orcid_id) WHERE orcid_id IS NOT NULL"
    )

    op.drop_index("ix_similarity_features_spectrum_id", table_name="similarity_features")
    op.create_index(
        "ix_similarity_features_spectrum_id",
        "similarity_features",
        ["spectrum_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "similarity_features_spectrum_id_key", "similarity_features", ["spectrum_id"]
    )

    op.drop_index("ix_publications_doi", table_name="publications")
    op.create_index("ix_publications_doi", "publications", ["doi"], unique=False)
    op.create_unique_constraint("publications_doi_key", "publications", ["doi"])

    for table, column in reversed(_TIMESTAMP_NOT_NULL):
        op.alter_column(
            table,
            column,
            existing_type=postgresql.TIMESTAMP(timezone=True),
            nullable=True,
            existing_server_default=sa.text("now()"),
        )

    op.drop_constraint(
        "uq_analysis_dataset_spectrum", "analysis_dataset_spectra", type_="unique"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_dataset_spectrum "
        "ON analysis_dataset_spectra (dataset_id, spectrum_id)"
    )
