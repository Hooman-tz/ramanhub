"""M3a (retarget): finding votes + comment threading, hardened.

This is the part that touches shipped data. `f2b1e9c4d7a3` only added the
nullable `finding_id` columns to `votes` / `comments`; this migration makes
finding engagement actually writable and safe:

- `votes.spectrum_id` becomes nullable, the old UNIQUE(spectrum_id, user_id)
  constraint is swapped for two PARTIAL unique indexes (it stops
  constraining finding-votes the moment spectrum_id can be NULL — Postgres
  treats NULLs as distinct), and a CHECK pins exactly one target.
- `comments` gains `parent_id` (one-level threading, depth enforced at the
  router) and its 2-way spectrum-XOR-post CHECK becomes a 3-way
  exactly-one-of spectrum / post / finding.

`comments.spectrum_id` is already nullable (the public-commons migration
dropped its NOT NULL), so it is left alone here.

Revision ID: e5b8d2fa4c36
Revises: d4a7c1e93b25
Create Date: 2026-08-29
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5b8d2fa4c36"
down_revision: str | Sequence[str] | None = "d4a7c1e93b25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- votes: retarget + partial-unique hardening --------------------
    op.alter_column("votes", "spectrum_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint("uq_vote_spectrum_user", "votes", type_="unique")
    op.create_index(
        "uq_vote_spectrum_user",
        "votes",
        ["spectrum_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("spectrum_id IS NOT NULL"),
    )
    op.create_index(
        "uq_vote_finding_user",
        "votes",
        ["finding_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("finding_id IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_vote_one_target",
        "votes",
        "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1",
    )

    # --- comments: threading + 3-way target CHECK ---------------------
    op.add_column("comments", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "comments_parent_id_fkey",
        "comments",
        "comments",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"], unique=False)
    op.drop_constraint("ck_comment_has_one_target", "comments", type_="check")
    op.create_check_constraint(
        "ck_comment_one_target",
        "comments",
        "(spectrum_id IS NOT NULL)::int + (post_id IS NOT NULL)::int "
        "+ (finding_id IS NOT NULL)::int = 1",
    )


def downgrade() -> None:
    # --- comments ----------------------------------------------------
    op.drop_constraint("ck_comment_one_target", "comments", type_="check")
    # Finding-targeted comments have a NULL spectrum_id and post_id and
    # cannot satisfy the restored 2-way check; drop them rather than fail.
    op.execute(
        "DELETE FROM comments WHERE spectrum_id IS NULL AND post_id IS NULL"
    )
    op.create_check_constraint(
        "ck_comment_has_one_target",
        "comments",
        "(spectrum_id IS NOT NULL) <> (post_id IS NOT NULL)",
    )
    op.drop_index("ix_comments_parent_id", table_name="comments")
    op.drop_constraint("comments_parent_id_fkey", "comments", type_="foreignkey")
    op.drop_column("comments", "parent_id")

    # --- votes -----------------------------------------------------
    op.drop_constraint("ck_vote_one_target", "votes", type_="check")
    op.drop_index("uq_vote_finding_user", table_name="votes")
    op.drop_index("uq_vote_spectrum_user", table_name="votes")
    # Finding-targeted votes have a NULL spectrum_id and cannot survive the
    # NOT NULL restore; drop them rather than fail the downgrade.
    op.execute("DELETE FROM votes WHERE spectrum_id IS NULL")
    op.alter_column("votes", "spectrum_id", existing_type=sa.UUID(), nullable=False)
    op.create_unique_constraint(
        "uq_vote_spectrum_user", "votes", ["spectrum_id", "user_id"]
    )
