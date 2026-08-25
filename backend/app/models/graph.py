"""The social graph: who follows whom, and the handles people used to have.

## Follow is asymmetric on purpose

There is no request/accept flow. Following is a subscription, not a
relationship — its job is to seed `/feed?filter=following`, turning a global
firehose into something worth coming back to. A symmetric connect flow would
add an obligation gradient and notification spam, and in academia it
degenerates into CV padding within weeks.

The genuine symmetric relation — who you actually worked with — is *derived*
from co-authorship (`FindingEntry.author_id` vs `Finding.owner_id`, and
`FindingSpectrum` membership) rather than asserted. That version cannot be
inflated without doing real joint work, so it needs no table here.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Follow(Base):
    """`follower_id` follows `followee_id`."""

    __tablename__ = "follows"
    __table_args__ = (
        # One follow per direction per pair. Without this, a double-click on
        # the follow button inflates a public, brag-worthy number.
        Index("uq_follow_pair", "follower_id", "followee_id", unique=True),
        # Self-following would let anyone add one to their own follower count
        # for free. Cheap to forbid in the schema, and then no router can
        # forget to check it.
        CheckConstraint("follower_id <> followee_id", name="ck_follow_not_self"),
        # The feed query is "everything published by anyone I follow", so it
        # reads by follower_id; the profile's follower count reads by
        # followee_id. Both directions get an index.
        Index("ix_follow_follower", "follower_id"),
        Index("ix_follow_followee", "followee_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    follower_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    followee_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class HandleHistory(Base):
    """A handle a user previously held, kept so `/u/<old>` can redirect.

    Handles are printed in papers and data-availability statements — that is
    the entire reason they exist rather than UUIDs. So a handle must never
    silently start resolving to a different person: that is the same failure
    the accession module refuses to allow, and it is worse here because the
    citation looks fine while pointing at a stranger.

    Two rules follow, both enforced by this table plus the router that reads
    it: an old handle redirects to its owner's current one, and a released
    handle is never re-issued to anyone else. `handle` is therefore unique
    across history, not merely unique per user.
    """

    __tablename__ = "handle_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    handle: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    user_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    released_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
