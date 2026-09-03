"""Add finding co-authors and next steps.

Two additions to the write-up, both for the same reason: a finding is meant to
be a piece of work other people can pick up.

- `findings.next_steps_md` — what the author thinks should happen next. Its own
  column rather than more prose in `abstract_md`, so a reader scanning for
  "can I help with this" doesn't have to read the whole write-up to find it.
- `finding_co_authors` — credits pointing at registered users. A join table
  rather than free-text names, because a credit is only useful if it links to
  the person's profile. External collaborators belong in the write-up or in
  the linked paper's Crossref author list.

Purely additive: one nullable column, one new table. Nothing existing changes,
so `downgrade` is a clean reversal.

Revision ID: b3e6f1a92c47
Revises: d9f1a4c7b2e6
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3e6f1a92c47"
down_revision: str | Sequence[str] | None = "d9f1a4c7b2e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("next_steps_md", sa.Text(), nullable=True))

    op.create_table(
        "finding_co_authors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_id", "user_id", name="uq_finding_co_author"),
    )
    op.create_index("ix_finding_co_authors_finding_id", "finding_co_authors", ["finding_id"])
    op.create_index("ix_finding_co_authors_user_id", "finding_co_authors", ["user_id"])
    op.create_index(
        "ix_finding_co_authors_finding_position",
        "finding_co_authors",
        ["finding_id", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_finding_co_authors_finding_position", table_name="finding_co_authors")
    op.drop_index("ix_finding_co_authors_user_id", table_name="finding_co_authors")
    op.drop_index("ix_finding_co_authors_finding_id", table_name="finding_co_authors")
    op.drop_table("finding_co_authors")
    op.drop_column("findings", "next_steps_md")
