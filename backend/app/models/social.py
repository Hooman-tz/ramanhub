"""Community interactions kept separate from objective scientific discovery.

Deliberately quarantined from core search/discovery — nothing here ever
feeds spectra ranking in app.routers.search; it only powers the separate
Trending feed (app.routers.trending).
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Exactly one of (spectrum_id, finding_id) is set. Load-bearing, not
# decorative: a row with both set would be counted twice (once per tally)
# and a row with neither would be an orphan no delete path reaches.
_ONE_OF_SPECTRUM_FINDING = (
    "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1"
)


class Vote(Base):
    """One upvote from one user on one spectrum or one finding. Presence of a
    row IS the vote (no direction/value column) — voting again removes it
    (toggle), handled at the router layer.
    """

    __tablename__ = "votes"
    __table_args__ = (
        CheckConstraint(_ONE_OF_SPECTRUM_FINDING, name="ck_vote_one_target"),
        # PARTIAL unique indexes, and the "partial" is the whole point.
        # Postgres treats NULLs as distinct, so a plain
        # UNIQUE(spectrum_id, user_id) would not constrain finding-votes at
        # all — every one of them has spectrum_id NULL. Restricting each
        # index to rows where its own target is NOT NULL makes each enforce
        # exactly the pair it is about.
        Index(
            "uq_vote_spectrum_user",
            "spectrum_id",
            "user_id",
            unique=True,
            postgresql_where=text("spectrum_id IS NOT NULL"),
        ),
        Index(
            "uq_vote_finding_user",
            "finding_id",
            "user_id",
            unique=True,
            postgresql_where=text("finding_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id = mapped_column(UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=True, index=True)
    finding_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    __tablename__ = "comments"
    # Exactly one of spectrum / community-post / finding is the target.
    __table_args__ = (
        CheckConstraint(
            "(spectrum_id IS NOT NULL)::int + (post_id IS NOT NULL)::int "
            "+ (finding_id IS NOT NULL)::int = 1",
            name="ck_comment_one_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id = mapped_column(UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=True, index=True)
    post_id = mapped_column(UUID(as_uuid=True), ForeignKey("community_posts.id"), nullable=True, index=True)
    finding_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Threaded replies. One level is enforced at the router, not here: deep
    # nesting turns a scientific discussion into an unreadable tree, and a
    # self-referencing FK can't express a depth limit anyway.
    parent_id = mapped_column(
        Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    moderation_status: Mapped[str] = mapped_column(
        String, nullable=False, default="visible", server_default=text("'visible'")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Share(Base):
    """One user re-broadcasting one spectrum or Finding into their followers'
    feeds.

    Same dual-target shape as `Vote`, and the same partial-unique-index
    reasoning applies verbatim — see the comment on `Vote.__table_args__`.
    A plain UNIQUE(spectrum_id, user_id) would leave finding-shares
    completely unconstrained, because every one of them has a NULL
    spectrum_id and Postgres treats NULLs as distinct.

    Why a table rather than a counter column: a share has to name *who*
    shared, or `filter=following` cannot surface "someone you follow shared
    this". `comment` lets a sharer add their own framing — the quote-post
    shape. Optional, because most shares are a bare signal boost.
    """

    __tablename__ = "shares"
    __table_args__ = (
        CheckConstraint(_ONE_OF_SPECTRUM_FINDING, name="ck_share_one_target"),
        Index(
            "uq_share_spectrum_user",
            "spectrum_id",
            "user_id",
            unique=True,
            postgresql_where=text("spectrum_id IS NOT NULL"),
        ),
        Index(
            "uq_share_finding_user",
            "finding_id",
            "user_id",
            unique=True,
            postgresql_where=text("finding_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=True, index=True
    )
    finding_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class CommunityPost(Base):
    """A research update or dataset announcement linked only to public work."""

    __tablename__ = "community_posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, server_default="announcement")
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    moderation_status: Mapped[str] = mapped_column(
        String, nullable=False, default="visible", server_default=text("'visible'")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CommunityPostSpectrum(Base):
    __tablename__ = "community_post_spectra"
    __table_args__ = (
        UniqueConstraint("post_id", "spectrum_id", name="uq_community_post_spectrum"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community_posts.id"), nullable=False, index=True
    )
    spectrum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=False, index=True
    )


class PostReaction(Base):
    __tablename__ = "post_reactions"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id", name="uq_post_reaction_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("community_posts.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Report(Base):
    __tablename__ = "community_reports"
    __table_args__ = (
        UniqueConstraint(
            "reporter_id", "target_type", "target_id", name="uq_community_reporter_target"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="open", server_default=text("'open'")
    )
    moderator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    in_app_enabled: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )
    comment_notifications: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )
    moderation_notifications: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Notification(Base):
    __tablename__ = "community_notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
