"""Add reproducible analysis artifacts and versioned similarity features.

Revision ID: c8f2a1d7e4b6
Revises: a4e7d2b8c6f1
Create Date: 2026-08-27
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c8f2a1d7e4b6"
down_revision: str | Sequence[str] | None = "a4e7d2b8c6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("modality", postgresql.ENUM("raman", "mass_spec", "nmr", name="modality", create_type=False), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "name", name="uq_analysis_dataset_owner_name"),
    )
    op.create_index("ix_analysis_datasets_owner_id", "analysis_datasets", ["owner_id"])
    op.create_table(
        "analysis_dataset_spectra",
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spectrum_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["analysis_datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spectrum_id"], ["spectra.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("dataset_id", "spectrum_id"),
        sa.UniqueConstraint("dataset_id", "spectrum_id", name="uq_analysis_dataset_spectrum"),
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("execution_backend", sa.String(length=20), server_default=sa.text("'local'"), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("software_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_checks", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("citation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("job_signature", sa.String(length=128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["analysis_datasets.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_dataset_id", "analysis_runs", ["dataset_id"])
    op.create_index("ix_analysis_runs_owner_id", "analysis_runs", ["owner_id"])
    op.create_index("ix_analysis_runs_status", "analysis_runs", ["status"])
    op.create_index("ix_analysis_runs_output_hash", "analysis_runs", ["output_hash"])
    op.create_table(
        "similarity_features",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("spectrum_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("modality", postgresql.ENUM("raman", "mass_spec", "nmr", name="modality", create_type=False), nullable=False),
        sa.Column("feature_version", sa.String(length=40), nullable=False),
        sa.Column("canonicalization_version", sa.String(length=40), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("wavenumber_min", sa.Float(), nullable=False),
        sa.Column("wavenumber_max", sa.Float(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("qc_eligible", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("qc_reasons", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["spectrum_id"], ["spectra.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spectrum_id"),
    )
    op.create_index("ix_similarity_features_spectrum_id", "similarity_features", ["spectrum_id"])


def downgrade() -> None:
    op.drop_table("similarity_features")
    op.drop_index("ix_analysis_runs_output_hash", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_status", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_owner_id", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_dataset_id", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_table("analysis_dataset_spectra")
    op.drop_index("ix_analysis_datasets_owner_id", table_name="analysis_datasets")
    op.drop_table("analysis_datasets")