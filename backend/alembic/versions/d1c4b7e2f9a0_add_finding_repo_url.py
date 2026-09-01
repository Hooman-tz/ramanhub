"""Add findings.repo_url — optional link to the code/analysis repo.

A write-up can point at the paper it became (`doi`); this lets it also point
at the code behind it (a GitHub repo, a notebook archive). Nullable,
free-text, not verified — a provenance breadcrumb, same role `doi` plays.

Revision ID: d1c4b7e2f9a0
Revises: c9d2e5f8a1b4
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1c4b7e2f9a0"
down_revision: str | Sequence[str] | None = "c9d2e5f8a1b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("repo_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "repo_url")
