"""M3a (2/2 additive): the `shares` table.

Re-broadcasting a spectrum or a Finding into a follower feed. Same
dual-target shape as `votes`: `spectrum_id` and `finding_id` both nullable,
a CHECK that exactly one is set, and two PARTIAL unique indexes (each
restricted to rows where its own target is NOT NULL) rather than a plain
UNIQUE — a plain UNIQUE(spectrum_id, user_id) would not constrain
finding-shares at all, since every one of them has spectrum_id NULL and
Postgres treats NULLs as distinct.

Revision ID: d4a7c1e93b25
Revises: f2b1e9c4d7a3
Create Date: 2026-08-29
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a7c1e93b25"
down_revision: str | Sequence[str] | None = "f2b1e9c4d7a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shares",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("spectrum_id", sa.UUID(), nullable=True),
        sa.Column("finding_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1",
            name="ck_share_one_target",
        ),
        sa.ForeignKeyConstraint(["spectrum_id"], ["spectra.id"]),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_shares_spectrum_id"), "shares", ["spectrum_id"], unique=False)
    op.create_index(op.f("ix_shares_finding_id"), "shares", ["finding_id"], unique=False)
    op.create_index(op.f("ix_shares_created_at"), "shares", ["created_at"], unique=False)
    op.create_index(
        "uq_share_spectrum_user",
        "shares",
        ["spectrum_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("spectrum_id IS NOT NULL"),
    )
    op.create_index(
        "uq_share_finding_user",
        "shares",
        ["finding_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("finding_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_share_finding_user", table_name="shares")
    op.drop_index("uq_share_spectrum_user", table_name="shares")
    op.drop_index(op.f("ix_shares_created_at"), table_name="shares")
    op.drop_index(op.f("ix_shares_finding_id"), table_name="shares")
    op.drop_index(op.f("ix_shares_spectrum_id"), table_name="shares")
    op.drop_table("shares")
