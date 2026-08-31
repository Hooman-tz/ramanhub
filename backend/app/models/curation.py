"""Owner-curated surface on a profile: pinned items.

A profile ordered only by recency is a log, and a log is a bad way to judge a
scientist — the work someone wants to be known for is frequently not the
thing they touched most recently. Pinning is what turns the page from a feed
into a portfolio.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_EXACTLY_ONE_TARGET = (
    "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1"
)

# Deliberately small. Pinning is only useful if it forces a choice; a profile
# that pins twenty items has ranked nothing.
MAX_PINS = 4


class Pin(Base):
    """One item a user has pinned to the top of their own profile.

    Dual-target with the same CHECK + partial-unique-index pattern as `Vote`
    in `app.models.social` — a plain unique constraint would leave
    finding-pins unconstrained, since every one of them has `spectrum_id`
    NULL and Postgres treats NULLs as distinct.
    """

    __tablename__ = "pins"
    __table_args__ = (
        CheckConstraint(_EXACTLY_ONE_TARGET, name="ck_pin_one_target"),
        Index(
            "uq_pin_spectrum_user",
            "spectrum_id",
            "user_id",
            unique=True,
            postgresql_where=text("spectrum_id IS NOT NULL"),
        ),
        Index(
            "uq_pin_finding_user",
            "finding_id",
            "user_id",
            unique=True,
            postgresql_where=text("finding_id IS NOT NULL"),
        ),
        Index("ix_pin_user_position", "user_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    spectrum_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id", ondelete="CASCADE"), nullable=True
    )
    finding_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
