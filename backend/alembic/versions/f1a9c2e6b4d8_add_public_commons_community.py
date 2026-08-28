"""Add public records, community interactions, and moderation controls.

Revision ID: f1a9c2e6b4d8
Revises: d83a6b1e5c7f
Create Date: 2026-08-27
"""
from collections.abc import Sequence

from alembic import op

revision: str = "f1a9c2e6b4d8"
down_revision: str | Sequence[str] | None = "d83a6b1e5c7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The initial social prototype was created by metadata bootstrap rather
    # than Alembic, so this migration deliberately tolerates those two tables
    # already existing in development installs.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS votes (
            id SERIAL PRIMARY KEY,
            spectrum_id UUID NOT NULL REFERENCES spectra(id),
            user_id UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_vote_spectrum_user UNIQUE (spectrum_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS ix_votes_spectrum_id ON votes (spectrum_id);

        CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY,
            spectrum_id UUID REFERENCES spectra(id),
            user_id UUID NOT NULL REFERENCES users(id),
            body TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_comments_spectrum_id ON comments (spectrum_id);
        """
    )
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN IF NOT EXISTS orcid_verified_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS orcid_name VARCHAR,
            ADD COLUMN IF NOT EXISTS profile_handle VARCHAR,
            ADD COLUMN IF NOT EXISTS bio TEXT,
            ADD COLUMN IF NOT EXISTS affiliation VARCHAR,
            ADD COLUMN IF NOT EXISTS research_interests JSONB,
            ADD COLUMN IF NOT EXISTS is_profile_public BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS is_moderator BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
        UPDATE users
        SET profile_handle = 'researcher-' || replace(id::text, '-', '')
        WHERE profile_handle IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_profile_handle
            ON users (profile_handle);

        CREATE TABLE IF NOT EXISTS publications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            doi VARCHAR NOT NULL UNIQUE,
            provider VARCHAR NOT NULL DEFAULT 'crossref',
            verification_status VARCHAR NOT NULL DEFAULT 'verified',
            snapshot JSONB NOT NULL,
            verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_publications_doi ON publications (doi);

        INSERT INTO publications (doi, provider, verification_status, snapshot, verified_at)
        SELECT DISTINCT ON (doi) doi, provider, verification_status, snapshot, verified_at
        FROM publication_snapshots
        WHERE verification_status = 'verified'
        ORDER BY doi, verified_at DESC
        ON CONFLICT (doi) DO NOTHING;

        ALTER TABLE spectra
            ADD COLUMN IF NOT EXISTS publication_id UUID REFERENCES publications(id),
            ADD COLUMN IF NOT EXISTS moderation_status VARCHAR NOT NULL DEFAULT 'visible';
        CREATE INDEX IF NOT EXISTS ix_spectra_publication_id ON spectra (publication_id);
        UPDATE spectra
        SET publication_id = publications.id
        FROM publication_snapshots
        JOIN publications ON publications.doi = publication_snapshots.doi
        WHERE publication_snapshots.spectrum_id = spectra.id
          AND publication_snapshots.verification_status = 'verified'
          AND spectra.publication_id IS NULL;

        CREATE TABLE IF NOT EXISTS community_posts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES users(id),
            publication_id UUID REFERENCES publications(id),
            kind VARCHAR NOT NULL DEFAULT 'announcement',
            title VARCHAR NOT NULL,
            body TEXT NOT NULL,
            moderation_status VARCHAR NOT NULL DEFAULT 'visible',
            deleted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_community_posts_owner_id ON community_posts (owner_id);
        CREATE INDEX IF NOT EXISTS ix_community_posts_publication_id ON community_posts (publication_id);

        CREATE TABLE IF NOT EXISTS community_post_spectra (
            id SERIAL PRIMARY KEY,
            post_id UUID NOT NULL REFERENCES community_posts(id),
            spectrum_id UUID NOT NULL REFERENCES spectra(id),
            CONSTRAINT uq_community_post_spectrum UNIQUE (post_id, spectrum_id)
        );
        CREATE INDEX IF NOT EXISTS ix_community_post_spectra_post_id ON community_post_spectra (post_id);
        CREATE INDEX IF NOT EXISTS ix_community_post_spectra_spectrum_id ON community_post_spectra (spectrum_id);

        CREATE TABLE IF NOT EXISTS post_reactions (
            id SERIAL PRIMARY KEY,
            post_id UUID NOT NULL REFERENCES community_posts(id),
            user_id UUID NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_post_reaction_user UNIQUE (post_id, user_id)
        );
        CREATE INDEX IF NOT EXISTS ix_post_reactions_post_id ON post_reactions (post_id);

        ALTER TABLE comments
            ALTER COLUMN spectrum_id DROP NOT NULL,
            ADD COLUMN IF NOT EXISTS post_id UUID REFERENCES community_posts(id),
            ADD COLUMN IF NOT EXISTS moderation_status VARCHAR NOT NULL DEFAULT 'visible',
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
        CREATE INDEX IF NOT EXISTS ix_comments_post_id ON comments (post_id);

        CREATE TABLE IF NOT EXISTS community_reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            reporter_id UUID NOT NULL REFERENCES users(id),
            target_type VARCHAR NOT NULL,
            target_id VARCHAR NOT NULL,
            reason VARCHAR NOT NULL,
            detail TEXT,
            status VARCHAR NOT NULL DEFAULT 'open',
            moderator_id UUID REFERENCES users(id),
            resolution_note TEXT,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_community_reporter_target UNIQUE (reporter_id, target_type, target_id)
        );
        CREATE INDEX IF NOT EXISTS ix_community_reports_reporter_id ON community_reports (reporter_id);
        CREATE INDEX IF NOT EXISTS ix_community_reports_target_type ON community_reports (target_type);
        CREATE INDEX IF NOT EXISTS ix_community_reports_target_id ON community_reports (target_id);

        CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id UUID PRIMARY KEY REFERENCES users(id),
            in_app_enabled BOOLEAN NOT NULL DEFAULT true,
            comment_notifications BOOLEAN NOT NULL DEFAULT true,
            moderation_notifications BOOLEAN NOT NULL DEFAULT true,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE IF NOT EXISTS community_notifications (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id),
            kind VARCHAR NOT NULL,
            payload JSONB NOT NULL,
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_community_notifications_user_id
            ON community_notifications (user_id);
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_comment_has_one_target'
            ) THEN
                ALTER TABLE comments
                    ADD CONSTRAINT ck_comment_has_one_target
                    CHECK ((spectrum_id IS NOT NULL) <> (post_id IS NOT NULL));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS community_notifications;
        DROP TABLE IF EXISTS notification_preferences;
        DROP TABLE IF EXISTS community_reports;
        DROP TABLE IF EXISTS post_reactions;
        DROP TABLE IF EXISTS community_post_spectra;
        DROP TABLE IF EXISTS community_posts;
        ALTER TABLE comments
            DROP CONSTRAINT IF EXISTS ck_comment_has_one_target,
            DROP COLUMN IF EXISTS deleted_at,
            DROP COLUMN IF EXISTS moderation_status,
            DROP COLUMN IF EXISTS post_id;
        ALTER TABLE spectra
            DROP COLUMN IF EXISTS moderation_status,
            DROP COLUMN IF EXISTS publication_id;
        DROP TABLE IF EXISTS publications;
        DROP INDEX IF EXISTS uq_users_profile_handle;
        ALTER TABLE users
            DROP COLUMN IF EXISTS deleted_at,
            DROP COLUMN IF EXISTS is_moderator,
            DROP COLUMN IF EXISTS is_profile_public,
            DROP COLUMN IF EXISTS research_interests,
            DROP COLUMN IF EXISTS affiliation,
            DROP COLUMN IF EXISTS bio,
            DROP COLUMN IF EXISTS profile_handle,
            DROP COLUMN IF EXISTS orcid_name,
            DROP COLUMN IF EXISTS orcid_verified_at;
        """
    )