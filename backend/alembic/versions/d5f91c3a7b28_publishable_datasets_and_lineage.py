"""Publishable datasets, dataset lineage, and the finding -> dataset link.

`analysis_datasets` began life as a strictly private project folder: no state,
no accession, and every read gated on `owner_id == user.id`. That made a post's
data a dead end — a reader could see the spectra a write-up discussed but had
nowhere to go and nothing to take with them.

This revision gives a dataset the same publish story spectra and findings
already have:

  * `accession` — minted from a new `dataset_accession_seq` at *publish* time,
    not at create time, so abandoned drafts don't burn citable identifiers.
    Existing rows stay NULL; they are drafts by definition.
  * `state` / `published_at` / `license_id` / `doi` — the same shape as
    `findings`, deliberately without `spectrum_state`'s `embargoed` member (see
    `DatasetState`'s docstring: the members carry their own embargo clocks).
  * `parent_dataset_id` — the container equivalent of
    `spectra.parent_spectrum_id`, written by the dataset fork endpoint. Self-FK,
    ON DELETE SET NULL, matching the "fork lineage is best-effort metadata"
    stance `spectra` already takes.

And `findings.dataset_id`, ON DELETE SET NULL: a post points at one "main
dataset", and deleting the folder must not delete the write-up about it.

Revision ID: d5f91c3a7b28
Revises: c7a4d2e8f019
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d5f91c3a7b28"
down_revision: str | Sequence[str] | None = "c7a4d2e8f019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATASET_STATE = postgresql.ENUM("draft", "published", name="dataset_state", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()

    DATASET_STATE.create(bind, checkfirst=True)

    # Gaps are harmless, reuse is not — see app/models/accession.py.
    op.execute("CREATE SEQUENCE IF NOT EXISTS dataset_accession_seq START 1")

    op.add_column("analysis_datasets", sa.Column("accession", sa.String(), nullable=True))
    op.add_column(
        "analysis_datasets",
        sa.Column("state", DATASET_STATE, nullable=False, server_default="draft"),
    )
    op.add_column(
        "analysis_datasets",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("analysis_datasets", sa.Column("license_id", sa.String(), nullable=True))
    op.add_column("analysis_datasets", sa.Column("doi", sa.String(), nullable=True))
    op.add_column(
        "analysis_datasets",
        sa.Column("parent_dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_unique_constraint("uq_analysis_dataset_accession", "analysis_datasets", ["accession"])
    op.create_index(
        "ix_analysis_datasets_accession", "analysis_datasets", ["accession"], unique=False
    )
    op.create_index(
        "ix_analysis_datasets_parent_dataset_id",
        "analysis_datasets",
        ["parent_dataset_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_analysis_datasets_license_id",
        "analysis_datasets",
        "licenses",
        ["license_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_analysis_datasets_parent_dataset_id",
        "analysis_datasets",
        "analysis_datasets",
        ["parent_dataset_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("findings", sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_findings_dataset_id", "findings", ["dataset_id"], unique=False)
    op.create_foreign_key(
        "fk_findings_dataset_id",
        "findings",
        "analysis_datasets",
        ["dataset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_constraint("fk_findings_dataset_id", "findings", type_="foreignkey")
    op.drop_index("ix_findings_dataset_id", table_name="findings")
    op.drop_column("findings", "dataset_id")

    op.drop_constraint(
        "fk_analysis_datasets_parent_dataset_id", "analysis_datasets", type_="foreignkey"
    )
    op.drop_constraint("fk_analysis_datasets_license_id", "analysis_datasets", type_="foreignkey")
    op.drop_index("ix_analysis_datasets_parent_dataset_id", table_name="analysis_datasets")
    op.drop_index("ix_analysis_datasets_accession", table_name="analysis_datasets")
    op.drop_constraint("uq_analysis_dataset_accession", "analysis_datasets", type_="unique")

    op.drop_column("analysis_datasets", "parent_dataset_id")
    op.drop_column("analysis_datasets", "doi")
    op.drop_column("analysis_datasets", "license_id")
    op.drop_column("analysis_datasets", "published_at")
    op.drop_column("analysis_datasets", "state")
    op.drop_column("analysis_datasets", "accession")

    op.execute("DROP SEQUENCE IF EXISTS dataset_accession_seq")
    DATASET_STATE.drop(bind, checkfirst=True)
