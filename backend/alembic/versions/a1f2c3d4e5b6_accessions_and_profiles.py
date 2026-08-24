"""accession IDs for spectra, public profile fields for users

Adds the two citable identifiers the platform was missing: a human-quotable
accession number per spectrum (RH-S-000042) and a URL handle per user
(/u/<handle>). See app/models/accession.py and app/models/handles.py for why
each exists.

Both columns are nullable with a unique index rather than NOT NULL. Existing
rows are backfilled below, but leaving them nullable means a future insert
that forgets to assign one fails loudly on use rather than blocking the
migration, and guest users legitimately have no public handle at all.

Revision ID: a1f2c3d4e5b6
Revises: e41f7a90c2d1
Create Date: 2026-08-24

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f2c3d4e5b6"
down_revision: str | Sequence[str] | None = "e41f7a90c2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- accession sequences -------------------------------------------
    op.execute("CREATE SEQUENCE IF NOT EXISTS spectrum_accession_seq START 1")
    op.execute("CREATE SEQUENCE IF NOT EXISTS finding_accession_seq START 1")

    # --- spectra.accession ---------------------------------------------
    op.add_column("spectra", sa.Column("accession", sa.String(), nullable=True))

    # Backfill in a stable order (oldest first) so accession numbers follow
    # creation order rather than whatever order the planner returns rows in
    # — an identifier series that reads as random would look broken.
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
    # Advance the sequence past everything just backfilled, so the first
    # newly-created spectrum can't collide with an existing accession.
    #
    # The third argument (`is_called`) is the subtle part. Two-argument
    # setval marks the value as already consumed, so nextval returns
    # value + 1 — which on an EMPTY table would set 1 as used and hand the
    # very first spectrum RH-S-000002, permanently burning RH-S-000001.
    # Passing `is_called = (count > 0)` makes the empty case start at 1
    # while a populated one still resumes after the last backfilled row.
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

    # --- users profile fields ------------------------------------------
    op.add_column("users", sa.Column("handle", sa.String(), nullable=True))
    op.add_column("users", sa.Column("affiliation", sa.String(), nullable=True))
    op.add_column("users", sa.Column("bio", sa.Text(), nullable=True))

    # Backfill handles from the email local part, sanitized to the same
    # [a-z0-9-] alphabet app/models/handles.py enforces, with a numeric
    # suffix for collisions. Guests (is_guest) are skipped: they have no
    # public profile, and their synthetic emails would produce noise
    # handles that permanently occupy names real users might want.
    op.execute(
        """
        WITH candidates AS (
            SELECT
                id,
                created_at,
                TRIM(BOTH '-' FROM REGEXP_REPLACE(
                    LOWER(SPLIT_PART(email, '@', 1)), '[^a-z0-9]+', '-', 'g'
                )) AS base
            FROM users
            WHERE is_guest = false
        ),
        numbered AS (
            SELECT
                id,
                CASE WHEN LENGTH(base) >= 3 THEN LEFT(base, 30) ELSE 'researcher' END AS base,
                ROW_NUMBER() OVER (
                    PARTITION BY CASE WHEN LENGTH(base) >= 3 THEN LEFT(base, 30)
                                 ELSE 'researcher' END
                    -- Earliest account wins the unsuffixed handle. Ordering
                    -- by id alone would hand it to whoever's random UUID
                    -- sorted first, which is arbitrary and unexplainable.
                    ORDER BY created_at, id
                ) AS rn
            FROM candidates
        )
        UPDATE users AS u
        SET handle = CASE WHEN numbered.rn = 1
                          THEN numbered.base
                          ELSE numbered.base || '-' || numbered.rn::text END
        FROM numbered
        WHERE u.id = numbered.id
        """
    )
    op.create_index(op.f("ix_users_handle"), "users", ["handle"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_handle"), table_name="users")
    op.drop_column("users", "bio")
    op.drop_column("users", "affiliation")
    op.drop_column("users", "handle")

    op.drop_index(op.f("ix_spectra_accession"), table_name="spectra")
    op.drop_column("spectra", "accession")

    op.execute("DROP SEQUENCE IF EXISTS finding_accession_seq")
    op.execute("DROP SEQUENCE IF EXISTS spectrum_accession_seq")
