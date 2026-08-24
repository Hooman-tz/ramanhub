"""Findings (forum threads) + retarget votes/comments to spectrum OR finding

The retarget is the only part of this that touches shipped data. It relaxes
votes.spectrum_id / comments.spectrum_id to nullable and adds finding_id
alongside, guarded by a CHECK that exactly one target is set.

The unique-index swap on `votes` is the subtle part and is done in this
order deliberately: the old UNIQUE(spectrum_id, user_id) constraint could
not stay, because once spectrum_id is nullable it stops constraining
finding-votes entirely (Postgres treats NULLs as distinct, so a user could
vote on one Finding without limit through rows whose spectrum_id is all
NULL). It's replaced by two PARTIAL unique indexes, each restricted to rows
where its own target is NOT NULL.

Revision ID: b2c3d4e5f6a7
Revises: a1f2c3d4e5b6
Create Date: 2026-08-24

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1f2c3d4e5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FINDING_STATE = postgresql.ENUM(
    "draft", "published", name="finding_state", create_type=False
)
FINDING_ENTRY_KIND = postgresql.ENUM(
    "note",
    "figure",
    "spectra",
    "peaks",
    "pca",
    "hca",
    "attachment",
    name="finding_entry_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    FINDING_STATE.create(bind, checkfirst=True)
    FINDING_ENTRY_KIND.create(bind, checkfirst=True)

    # --- findings -------------------------------------------------------
    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("accession", sa.String(), nullable=True),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("abstract_md", sa.Text(), nullable=True),
        sa.Column("state", FINDING_STATE, server_default="draft", nullable=False),
        sa.Column("license_id", sa.String(), nullable=True),
        sa.Column("doi", sa.String(), nullable=True),
        sa.Column("publication_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["license_id"], ["licenses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_findings_accession"), "findings", ["accession"], unique=True)
    op.create_index(op.f("ix_findings_owner_id"), "findings", ["owner_id"], unique=False)
    op.create_index(op.f("ix_findings_state"), "findings", ["state"], unique=False)
    op.create_index(op.f("ix_findings_doi"), "findings", ["doi"], unique=False)
    op.create_index(
        op.f("ix_findings_published_at"), "findings", ["published_at"], unique=False
    )

    op.create_table(
        "finding_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", FINDING_ENTRY_KIND, nullable=False),
        sa.Column("body_md", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_finding_entries_finding_position",
        "finding_entries",
        ["finding_id", "position"],
        unique=False,
    )

    op.create_table(
        "finding_spectra",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("spectrum_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spectrum_id"], ["spectra.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("finding_id", "spectrum_id", name="uq_finding_spectrum"),
    )
    op.create_index(
        op.f("ix_finding_spectra_finding_id"), "finding_spectra", ["finding_id"], unique=False
    )
    op.create_index(
        op.f("ix_finding_spectra_spectrum_id"), "finding_spectra", ["spectrum_id"], unique=False
    )

    # --- accession sequence for findings --------------------------------
    # (created in the previous migration; nothing to do here)

    # --- votes: retarget ------------------------------------------------
    op.add_column("votes", sa.Column("finding_id", sa.UUID(), nullable=True))
    op.alter_column("votes", "spectrum_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        "votes_finding_id_fkey", "votes", "findings", ["finding_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_votes_finding_id"), "votes", ["finding_id"], unique=False)
    op.create_index(op.f("ix_votes_created_at"), "votes", ["created_at"], unique=False)

    # Swap the old full unique constraint for two partial ones. See the
    # module docstring for why a plain UNIQUE stops working here.
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

    # --- comments: retarget + threading ---------------------------------
    op.add_column("comments", sa.Column("finding_id", sa.UUID(), nullable=True))
    op.add_column("comments", sa.Column("parent_id", sa.Integer(), nullable=True))
    op.alter_column("comments", "spectrum_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        "comments_finding_id_fkey",
        "comments",
        "findings",
        ["finding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "comments_parent_id_fkey",
        "comments",
        "comments",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_comments_finding_id"), "comments", ["finding_id"], unique=False)
    op.create_index(op.f("ix_comments_parent_id"), "comments", ["parent_id"], unique=False)
    op.create_check_constraint(
        "ck_comment_one_target",
        "comments",
        "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_comment_one_target", "comments", type_="check")
    op.drop_index(op.f("ix_comments_parent_id"), table_name="comments")
    op.drop_index(op.f("ix_comments_finding_id"), table_name="comments")
    op.drop_constraint("comments_parent_id_fkey", "comments", type_="foreignkey")
    op.drop_constraint("comments_finding_id_fkey", "comments", type_="foreignkey")
    # Finding-targeted rows have a NULL spectrum_id and cannot survive the
    # NOT NULL restore; drop them rather than failing the downgrade.
    op.execute("DELETE FROM comments WHERE spectrum_id IS NULL")
    op.alter_column("comments", "spectrum_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("comments", "parent_id")
    op.drop_column("comments", "finding_id")

    op.drop_constraint("ck_vote_one_target", "votes", type_="check")
    op.drop_index("uq_vote_finding_user", table_name="votes")
    op.drop_index("uq_vote_spectrum_user", table_name="votes")
    op.drop_index(op.f("ix_votes_created_at"), table_name="votes")
    op.drop_index(op.f("ix_votes_finding_id"), table_name="votes")
    op.drop_constraint("votes_finding_id_fkey", "votes", type_="foreignkey")
    op.execute("DELETE FROM votes WHERE spectrum_id IS NULL")
    op.alter_column("votes", "spectrum_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("votes", "finding_id")
    op.create_unique_constraint("uq_vote_spectrum_user", "votes", ["spectrum_id", "user_id"])

    op.drop_index(op.f("ix_finding_spectra_spectrum_id"), table_name="finding_spectra")
    op.drop_index(op.f("ix_finding_spectra_finding_id"), table_name="finding_spectra")
    op.drop_table("finding_spectra")
    op.drop_index("ix_finding_entries_finding_position", table_name="finding_entries")
    op.drop_table("finding_entries")
    for index in (
        "ix_findings_published_at",
        "ix_findings_doi",
        "ix_findings_state",
        "ix_findings_owner_id",
        "ix_findings_accession",
    ):
        op.drop_index(op.f(index), table_name="findings")
    op.drop_table("findings")

    bind = op.get_bind()
    FINDING_ENTRY_KIND.drop(bind, checkfirst=True)
    FINDING_STATE.drop(bind, checkfirst=True)
