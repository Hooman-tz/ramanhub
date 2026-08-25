"""Owner-curated surfaces on a profile: pinned items and collections.

Both exist for the same reason. A profile ordered only by recency is a log,
and a log is a bad way to judge a scientist — the work someone wants to be
known for is frequently not the thing they touched most recently. Curation is
what turns the page from a feed into a portfolio.
"""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_EXACTLY_ONE_TARGET = "(spectrum_id IS NOT NULL)::int + (finding_id IS NOT NULL)::int = 1"

# Deliberately small. Pinning is only useful if it forces a choice; a profile
# that pins twenty items has ranked nothing.
MAX_PINS = 4


class Pin(Base):
    """One item a user has pinned to the top of their own profile.

    Dual-target with the same CHECK + partial-unique-index pattern as `Vote`
    in `app.models.social` — see that module for why a plain unique
    constraint would leave finding-pins unconstrained.
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


class Collection(Base):
    """An owner-named, ordered set of spectra — "SERS substrates 2025".

    Spectra only, not Findings. A collection's payload is a *grid of
    thumbnails*, and that only means anything for objects that plot; a
    Finding is a narrative thread with no useful thumbnail. Mixing them would
    produce a grid half full of placeholder tiles.
    """

    __tablename__ = "collections"
    __table_args__ = (
        # Slugs are per-owner, so two people may both have "sers-substrates".
        Index("uq_collection_owner_slug", "owner_id", "slug", unique=True),
    )

    id = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CollectionSpectrum(Base):
    """Ordered membership of a spectrum in a collection.

    Mirrors `FindingSpectrum`: a link row with an explicit `position`, because
    the order a scientist arranges a series in (concentration, temperature,
    time point) carries meaning that insertion order does not.
    """

    __tablename__ = "collection_spectra"
    __table_args__ = (
        Index("uq_collection_spectrum", "collection_id", "spectrum_id", unique=True),
        Index("ix_collection_spectrum_position", "collection_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    spectrum_id = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
