"""Add idempotency_records — request idempotency for mutating handlers.

Backs `app.idempotency`: a `(user_id, idem_key)` row lets a replayed POST
(proxy retry / HTTP/2 stream reset carrying the same client `Idempotency-Key`
header) return the first run's stored response instead of creating a second
draft / post / vote.

Purely additive: one new table, no change to any existing one.

Revision ID: d9f1a4c7b2e6
Revises: af117c4589e4
Create Date: 2026-09-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d9f1a4c7b2e6"
down_revision: str | Sequence[str] | None = "af117c4589e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("idem_key", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idem_key", name="uq_idempotency_user_key"),
    )
    op.create_index(
        op.f("ix_idempotency_records_user_id"),
        "idempotency_records",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_idempotency_records_user_id"), table_name="idempotency_records"
    )
    op.drop_table("idempotency_records")
