"""M6.1: SCImago journals lookup table.

Adds `journals` — one row per ISSN, imported from the SCImago Journal Rank
CSV by `scripts/import_scimago.py` — so `link-doi` can enrich a Finding's
`publication_metadata` with quartile / SJR / cover image from whichever ISSN
Crossref returned for the paper.

Revision ID: f7c3a9e1d2b5
Revises: a7f3c1d9e2b4
Create Date: 2026-08-30
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7c3a9e1d2b5"
down_revision: str | Sequence[str] | None = "a7f3c1d9e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issn", sa.String(), nullable=False),
        sa.Column("issn_l", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("sjr", sa.Float(), nullable=True),
        sa.Column("quartile", sa.String(length=2), nullable=True),
        sa.Column("h_index", sa.Integer(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("sjr_year", sa.Integer(), nullable=True),
        sa.Column("cover_url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), server_default="scimago", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_journals_issn"), "journals", ["issn"], unique=True)
    op.create_index(op.f("ix_journals_issn_l"), "journals", ["issn_l"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_journals_issn_l"), table_name="journals")
    op.drop_index(op.f("ix_journals_issn"), table_name="journals")
    op.drop_table("journals")
