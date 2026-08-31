"""M6.2: finding images (author figures + graphical abstract).

Adds `finding_images` — raster images a user attaches to a Finding (figures,
a graphical abstract) that, unlike analysis entries, can't be recomputed from
spectra. They live in the same object store as the owner's spectra; this
table holds the object-store coordinates plus ordering / caption metadata.

Revision ID: b2e6f4a1c9d7
Revises: f7c3a9e1d2b5
Create Date: 2026-08-30
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2e6f4a1c9d7"
down_revision: str | Sequence[str] | None = "f7c3a9e1d2b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finding_images",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("caption", sa.String(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("storage_bucket", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('figure', 'graphical_abstract')", name="ck_finding_image_kind"
        ),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "finding_id", "content_hash", name="uq_finding_image_hash"
        ),
    )
    op.create_index(
        op.f("ix_finding_images_finding_id"),
        "finding_images",
        ["finding_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_finding_images_content_hash"),
        "finding_images",
        ["content_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_finding_images_content_hash"), table_name="finding_images")
    op.drop_index(op.f("ix_finding_images_finding_id"), table_name="finding_images")
    op.drop_table("finding_images")
