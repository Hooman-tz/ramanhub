"""Let a user route LLM work through their own provider key.

Every LLM-backed feature — ingestion header parsing, file-structure
detection, DOI abstract enrichment, filename suggestions, the lab consultant
— has until now run against the platform's shared OpenRouter account. That
means a user's spectra headers and questions transit our key, and everyone
shares the free tier's per-day request ceiling.

This revision adds `user_llm_credentials`: one row per user holding a
provider slug, an optional model slug, and their API key encrypted at rest
with Fernet (`app/security/secrets.py`). The plaintext key is never stored
and never returned by the API; `key_last4` exists only so the settings page
can show which key is saved.

`user_id` is the primary key rather than a surrogate id — this is a setting,
not a history, and replacing a key overwrites the row.

Purely additive: no existing table or column is touched, and a deployment
with no `LLM_KEY_ENCRYPTION_KEY` set simply never writes to it. `downgrade`
is a clean reversal (it drops the table, which discards stored keys — users
would re-enter them).

Revision ID: e2b8c5a71d43
Revises: b3e6f1a92c47
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e2b8c5a71d43"
down_revision: str | Sequence[str] | None = "b3e6f1a92c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_llm_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("key_last4", sa.String(length=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_llm_credentials")
