"""Findings threads, the follow graph, and citable accessions (M1).

Cherry-picked from the Track A social layer onto the Track B head. This is
the *additive* subset: new tables (findings / finding_entries /
finding_spectra / follows / handle_history), new nullable columns
(spectra.accession, users.onboarded_at, votes.finding_id,
comments.finding_id), and the two accession sequences.

Deliberately NOT here (lands in M3, when finding votes/comments are first
written): making votes.spectrum_id / comments.spectrum_id nullable, the
partial-unique-index swap on votes, the 3-way target CHECK constraints, and
comments.parent_id threading.

Revision ID: f2b1e9c4d7a3
Revises: c8f2a1d7e4b6
Create Date: 2026-08-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f2b1e9c4d7a3"
down_revision: str | Sequence[str] | None = "c8f2a1d7e4b6"
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

    # --- accession sequences -----------------------------------------------
    op.execute("CREATE SEQUENCE IF NOT EXISTS spectrum_accession_seq START 1")
    op.execute("CREATE SEQUENCE IF NOT EXISTS finding_accession_seq START 1")

    # --- spectra.accession + backfill ------------------------------------
    op.add_column("spectra", sa.Column("accession", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE spectra AS s
        SET accession = 'RH-S-' || LPAD(ordered.seq::text, 6, '0')
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS seq
            FROM spectra
        ) AS ordered
        WHERE s.id = ordered.id
        """
    )
    # Advance the sequence past the backfill. `is_called = (count > 0)` so an
    # empty table still hands the first spectrum RH-S-000001 rather than
    # burning it.
    op.execute(
        """
        SELECT setval(
            'spectrum_accession_seq',
            GREATEST((SELECT COUNT(*) FROM spectra), 1),
            (SELECT COUNT(*) FROM spectra) > 0
        )
        """
    )
    op.create_index(op.f("ix_spectra_accession"), "spectra", ["accession"], unique=True)

    # --- finding enums ---------------------------------------------------
    FINDING_STATE.create(bind, checkfirst=True)
    FINDING_ENTRY_KIND.create(bind, checkfirst=True)

    # --- findings ------------------------------------------------------
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

    # --- follow graph -------------------------------------------------
    op.create_table(
        "follows",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("follower_id", sa.UUID(), nullable=False),
        sa.Column("followee_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["followee_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("follower_id <> followee_id", name="ck_follow_not_self"),
    )
    op.create_index("uq_follow_pair", "follows", ["follower_id", "followee_id"], unique=True)
    op.create_index("ix_follow_follower", "follows", ["follower_id"], unique=False)
    op.create_index("ix_follow_followee", "follows", ["followee_id"], unique=False)
    op.create_index("ix_follows_created_at", "follows", ["created_at"], unique=False)

    op.create_table(
        "handle_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("handle", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "released_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_handle_history_handle"), "handle_history", ["handle"], unique=True)
    op.create_index(
        op.f("ix_handle_history_user_id"), "handle_history", ["user_id"], unique=False
    )

    # --- users.onboarded_at ------------------------------------------
    op.add_column(
        "users", sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True)
    )

    # --- votes / comments: finding_id column only (retarget is M3) ---
    op.add_column("votes", sa.Column("finding_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "votes_finding_id_fkey", "votes", "findings", ["finding_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_votes_finding_id"), "votes", ["finding_id"], unique=False)

    op.add_column("comments", sa.Column("finding_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "comments_finding_id_fkey",
        "comments",
        "findings",
        ["finding_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_comments_finding_id"), "comments", ["finding_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_comments_finding_id"), table_name="comments")
    op.drop_constraint("comments_finding_id_fkey", "comments", type_="foreignkey")
    op.drop_column("comments", "finding_id")

    op.drop_index(op.f("ix_votes_finding_id"), table_name="votes")
    op.drop_constraint("votes_finding_id_fkey", "votes", type_="foreignkey")
    op.drop_column("votes", "finding_id")

    op.drop_column("users", "onboarded_at")

    op.drop_index(op.f("ix_handle_history_user_id"), table_name="handle_history")
    op.drop_index(op.f("ix_handle_history_handle"), table_name="handle_history")
    op.drop_table("handle_history")

    op.drop_index("ix_follows_created_at", table_name="follows")
    op.drop_index("ix_follow_followee", table_name="follows")
    op.drop_index("ix_follow_follower", table_name="follows")
    op.drop_index("uq_follow_pair", table_name="follows")
    op.drop_table("follows")

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

    op.drop_index(op.f("ix_spectra_accession"), table_name="spectra")
    op.drop_column("spectra", "accession")
    op.execute("DROP SEQUENCE IF EXISTS finding_accession_seq")
    op.execute("DROP SEQUENCE IF EXISTS spectrum_accession_seq")
