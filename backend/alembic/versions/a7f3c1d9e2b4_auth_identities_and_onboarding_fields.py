"""auth identities and onboarding fields (M3b / M3c)

Beta signup is Google + GitHub + ORCID OAuth. This migration replaces the
single `users.google_sub` identity column with an `auth_identities` table
(one row per linked provider), so a second provider can resolve to the same
account and email/password can later be added as just another `provider`
value rather than a schema change.

`users.google_sub` / `users.email` become nullable: new OAuth sign-ups get
an `AuthIdentity` row instead of a `google_sub`, and ORCID sign-in yields no
email at all. Existing google_sub values (real accounts and `guest:*`
sessions) are left in place; the real ones are backfilled into
`auth_identities` as `provider='google'` rows.

Note: `users.is_profile_public` and `users.research_interests` already exist
(added in f1a9c2e6b4d8), and `users.onboarded_at` already exists (added in
f2b1e9c4d7a3), so M3c reuses them rather than adding parallel columns.

Revision ID: a7f3c1d9e2b4
Revises: e5b8d2fa4c36
Create Date: 2026-08-29
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7f3c1d9e2b4"
down_revision: str | Sequence[str] | None = "e5b8d2fa4c36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_identities",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_subject", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_subject", name="uq_auth_identity_provider_subject"
        ),
    )
    op.create_index(
        "ix_auth_identities_user_id", "auth_identities", ["user_id"], unique=False
    )

    # Identity now lives in auth_identities; a Google-less / email-less
    # account (GitHub before its email is fetched, ORCID sign-in) must be
    # representable.
    op.alter_column("users", "google_sub", existing_type=sa.String(), nullable=True)
    op.alter_column("users", "email", existing_type=sa.String(), nullable=True)

    # Backfill: every real (non-guest) Google account becomes a
    # provider='google' identity row. Guests (`guest:*`) and delete
    # tombstones (`deleted:*`) are deliberately excluded.
    op.execute(
        """
        INSERT INTO auth_identities (id, user_id, provider, provider_subject, email, created_at)
        SELECT gen_random_uuid(), id, 'google', google_sub, email, now()
        FROM users
        WHERE google_sub IS NOT NULL
          AND google_sub NOT LIKE 'guest:%'
          AND google_sub NOT LIKE 'deleted:%'
        ON CONFLICT ON CONSTRAINT uq_auth_identity_provider_subject DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")

    # `users.google_sub` / `users.email` are intentionally left NULLABLE on
    # downgrade. Restoring NOT NULL would require either deleting every user
    # that signed up via GitHub/ORCID (cascading into their spectra,
    # findings, ledgers and published records) or inventing placeholder
    # credentials that violate the columns' semantics. Both are worse than a
    # looser constraint, so the nullability change is treated as one-way.
    # Re-running `upgrade` is safe: the ALTERs are idempotent and the
    # backfill uses ON CONFLICT DO NOTHING.
