"""M6.3: profile pins.

Adds `pins` — the owner-curated top of a profile. Dual-target (a pin points
at exactly one spectrum OR one finding), same shape as `votes` / `shares`: a
CHECK that exactly one target column is set, plus two PARTIAL unique indexes
(each restricted to rows where its own target is NOT NULL) rather than a plain
UNIQUE, which would not constrain finding-pins at all since every one of them
has `spectrum_id` NULL and Postgres treats NULLs as distinct.

Revision ID: c9d2e5f8a1b4
Revises: b2e6f4a1c9d7
Create Date: 2026-08-30
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d2e5f8a1b4"
down_revision: str | Sequence[str] | None = "b2e6f4a1c9d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("spectrum_id", sa.UUID(), nullable=True),
        sa.Column("finding_id", sa.UUID(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1",
            name="ck_pin_one_target",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spectrum_id"], ["spectra.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_pin_spectrum_user",
        "pins",
        ["spectrum_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("spectrum_id IS NOT NULL"),
    )
    op.create_index(
        "uq_pin_finding_user",
        "pins",
        ["finding_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("finding_id IS NOT NULL"),
    )
    op.create_index("ix_pin_user_position", "pins", ["user_id", "position"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pin_user_position", table_name="pins")
    op.drop_index("uq_pin_finding_user", table_name="pins")
    op.drop_index("uq_pin_spectrum_user", table_name="pins")
    op.drop_table("pins")
