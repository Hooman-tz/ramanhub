"""Enforce one proof-of-control ORCID link per active account.

Revision ID: a4e7d2b8c6f1
Revises: f1a9c2e6b4d8
Create Date: 2026-08-27
"""
from collections.abc import Sequence

from alembic import op

revision: str = "a4e7d2b8c6f1"
down_revision: str | Sequence[str] | None = "f1a9c2e6b4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Preserve the oldest existing association if an older development
    # database contains duplicates; later rows must link again through ORCID.
    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (
                PARTITION BY orcid_id ORDER BY created_at ASC, id ASC
            ) AS ordinal
            FROM users
            WHERE orcid_id IS NOT NULL
        )
        UPDATE users
        SET orcid_id = NULL, orcid_verified_at = NULL, orcid_name = NULL
        FROM ranked
        WHERE users.id = ranked.id AND ranked.ordinal > 1;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_orcid_id
            ON users (orcid_id) WHERE orcid_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_orcid_id;")