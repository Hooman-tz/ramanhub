"""Upvotes, comments and shares — each on either a spectrum or a Finding.

Both tables carry `spectrum_id` and `finding_id`, each nullable, with a CHECK
constraint that exactly one is set. The alternative designs were worse: a
generic (target_type, target_id) pair gives up foreign keys entirely, and
separate `finding_votes` / `finding_comments` tables would duplicate every
query and every rate limit.

The constraint is load-bearing, not decorative. Without it a row with both
IDs set would be counted twice — once in the spectrum's tally and once in
the Finding's — and a row with neither would be an orphan that no delete
path ever reaches.

Careful when querying: `Vote.spectrum_id == x` is correct for a spectrum's
tally precisely BECAUSE the constraint guarantees finding-votes have a NULL
spectrum_id. Any query that filters on user/date alone now spans both kinds
and must say which it means — Trending in particular ranks spectra only.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_EXACTLY_ONE_TARGET = "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1"


class Vote(Base):
    """One upvote from one user on one spectrum or Finding. Presence of a
    row IS the vote (no direction/value column) — voting again removes it
    (toggle), handled at the router layer."""

    __tablename__ = "votes"
    __table_args__ = (
        CheckConstraint(_EXACTLY_ONE_TARGET, name="ck_vote_one_target"),
        # PARTIAL unique indexes, and the "partial" is the whole point.
        #
        # Postgres treats NULLs as distinct in a unique index, so a plain
        # UNIQUE(spectrum_id, user_id) would not constrain finding-votes at
        # all — every one of them has spectrum_id NULL, and NULL never
        # equals NULL, so a user could vote on the same Finding without
        # limit. Restricting each index to rows where its own target column
        # is NOT NULL makes each one enforce exactly the pair it's about.
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
    spectrum_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=True, index=True
    )
    finding_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Comment(Base):
    __tablename__ = "comments"
    __table_args__ = (CheckConstraint(_EXACTLY_ONE_TARGET, name="ck_comment_one_target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=True, index=True
    )
    finding_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    # Threaded replies. One level is enforced at the router, not here: deep
    # nesting turns a scientific discussion into an unreadable tree, and a
    # self-referencing FK can't express a depth limit anyway.
    parent_id = mapped_column(
        Integer, ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
    this", which is the entire point of the feature. A bare integer would
    also be trivially inflatable, whereas one row per (user, target) is
    bounded by the unique index at one share per person per item.

    `comment` lets a sharer add their own framing — the quote-post shape.
    Optional, because most shares are a bare signal boost.
    """

    __tablename__ = "shares"
    __table_args__ = (
        CheckConstraint(_EXACTLY_ONE_TARGET, name="ck_share_one_target"),
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
