"""add users.is_guest for guest (try-before-login) sessions

Revision ID: e41f7a90c2d1
Revises: b22da08c1678
Create Date: 2026-08-19
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e41f7a90c2d1"
down_revision = "b22da08c1678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("users", "is_guest")
