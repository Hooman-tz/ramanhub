"""A user's own LLM provider credential.

By default every LLM-backed feature (ingestion header parsing, structure
detection, DOI enrichment, filename suggestions, the lab consultant) runs
against the platform's OpenRouter key, which means the user's header text
and questions transit our account. A user who would rather that not happen —
or who simply wants a specific model — stores a key here, and every one of
those five call sites routes through it instead. See app/llm_credentials.py
for the resolution order.

One row per user (`user_id` is the primary key): this is a setting, not a
history. Replacing a key overwrites the row.

The key itself is Fernet-encrypted at rest (app/security/secrets.py) and is
never returned by any endpoint — `key_last4` exists so the UI can show the
user which key is stored without the server ever handing it back.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserLLMCredential(Base):
    __tablename__ = "user_llm_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # One of the preset slugs in app/llm_credentials.PROVIDERS. Stored as a
    # plain string rather than a DB enum so adding a provider is a code
    # change, not a migration; the API validates against the allowlist.
    provider: Mapped[str] = mapped_column(String, nullable=False)
    # NULL means "the provider's default model" — the user pasted a key but
    # did not care which model it reaches.
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    # Fernet token (urlsafe base64). Never logged, never returned.
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Display only, so the settings page can render "••••1234".
    key_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
        onupdate=text("now()"),
        nullable=False,
    )
