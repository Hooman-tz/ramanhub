"""Harden Raman ingestion, provenance, and publication evidence.

Revision ID: c61d7f4a2b9e
Revises: e41f7a90c2d1
Create Date: 2026-08-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c61d7f4a2b9e"
down_revision: str | Sequence[str] | None = "e41f7a90c2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("raw_files", sa.Column("dedupe_hash", sa.String(), nullable=True))
    op.add_column("raw_files", sa.Column("storage_version", sa.String(), nullable=True))
    op.add_column(
        "raw_files", sa.Column("checksum_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        "uq_raw_file_owner_dedupe_hash", "raw_files", ["owner_id", "dedupe_hash"]
    )

    op.add_column("ingestion_jobs", sa.Column("parser_version", sa.String(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("parser_confidence", sa.Float(), nullable=True))
    op.add_column("ingestion_jobs", sa.Column("canonicalization_version", sa.String(), nullable=True))
    op.add_column(
        "ingestion_jobs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "ingestion_jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3")
    )
    op.add_column("ingestion_jobs", sa.Column("run_after", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ingestion_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "ingestion_jobs", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "ingestion_jobs",
        sa.Column("draft_spectrum_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_ingestion_job_raw_file", "ingestion_jobs", ["raw_file_id"]
    )
    op.create_unique_constraint(
        "uq_ingestion_jobs_draft_spectrum_id", "ingestion_jobs", ["draft_spectrum_id"]
    )
    op.create_foreign_key(
        "fk_ingestion_jobs_draft_spectrum_id",
        "ingestion_jobs",
        "spectra",
        ["draft_spectrum_id"],
        ["id"],
    )

    op.add_column("processing_ledgers", sa.Column("processing_environment", postgresql.JSONB(), nullable=True))

    op.add_column("spectra", sa.Column("quality_flags", postgresql.JSONB(), nullable=True))
    op.add_column("spectra", sa.Column("canonicalization_version", sa.String(), nullable=True))
    op.add_column(
        "spectra", sa.Column("parent_spectrum_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_spectra_parent_spectrum_id", "spectra", ["parent_spectrum_id"])
    op.create_foreign_key(
        "fk_spectra_parent_spectrum_id",
        "spectra",
        "spectra",
        ["parent_spectrum_id"],
        ["id"],
    )

    op.create_table(
        "publication_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("spectrum_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doi", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), server_default="crossref", nullable=False),
        sa.Column("verification_status", sa.String(), server_default="verified", nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "verified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["spectrum_id"], ["spectra.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spectrum_id"),
    )
    op.create_index("ix_publication_snapshots_doi", "publication_snapshots", ["doi"])


def downgrade() -> None:
    op.drop_index("ix_publication_snapshots_doi", table_name="publication_snapshots")
    op.drop_table("publication_snapshots")

    op.drop_constraint("fk_spectra_parent_spectrum_id", "spectra", type_="foreignkey")
    op.drop_index("ix_spectra_parent_spectrum_id", table_name="spectra")
    op.drop_column("spectra", "parent_spectrum_id")
    op.drop_column("spectra", "canonicalization_version")
    op.drop_column("spectra", "quality_flags")

    op.drop_column("processing_ledgers", "processing_environment")

    op.drop_constraint("fk_ingestion_jobs_draft_spectrum_id", "ingestion_jobs", type_="foreignkey")
    op.drop_constraint(
        "uq_ingestion_jobs_draft_spectrum_id", "ingestion_jobs", type_="unique"
    )
    op.drop_constraint("uq_ingestion_job_raw_file", "ingestion_jobs", type_="unique")
    op.drop_column("ingestion_jobs", "draft_spectrum_id")
    op.drop_column("ingestion_jobs", "last_heartbeat_at")
    op.drop_column("ingestion_jobs", "lease_expires_at")
    op.drop_column("ingestion_jobs", "run_after")
    op.drop_column("ingestion_jobs", "max_attempts")
    op.drop_column("ingestion_jobs", "attempt_count")
    op.drop_column("ingestion_jobs", "canonicalization_version")
    op.drop_column("ingestion_jobs", "parser_confidence")
    op.drop_column("ingestion_jobs", "parser_version")

    op.drop_constraint("uq_raw_file_owner_dedupe_hash", "raw_files", type_="unique")
    op.drop_column("raw_files", "checksum_verified_at")
    op.drop_column("raw_files", "storage_version")
    op.drop_column("raw_files", "dedupe_hash")