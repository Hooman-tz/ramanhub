import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    google_sub: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    orcid_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    orcid_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    orcid_name: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_handle: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    affiliation: Mapped[str | None] = mapped_column(String, nullable=True)
    research_interests: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    is_profile_public: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    is_moderator: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    # Guest sessions: a real User row (so every ownership/row-level-access
    # check works unchanged) minted without Google login, with synthetic
    # google_sub/email. Guests can upload and run the processing tools;
    # identity-carrying actions (publish, vote, comment, profile/ORCID)
    # require a full account — see app.auth.deps.get_current_full_user.
    # Signing in with Google migrates a guest's work to the real account
    # (see app.routers.auth).
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
