"""Author-supplied images for a Finding: figures and the graphical abstract.

Analysis entries (see `app.models.finding`) deliberately store *parameters*
and recompute their figure from live spectrum data on every view. That does
not cover the images a write-up also needs — a micrograph, an instrument
photo, a hand-drawn scheme, the journal's graphical abstract — none of which
can be regenerated from spectra. Those are the user's own data, so they live
in the same object store as their spectra, keyed under the owner. This table
holds the object-store coordinates plus ordering / caption metadata; the
bytes stream back through the API's own `/file` route.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# The two roles an attached image can play. A CHECK (not a Postgres ENUM) —
# the set is tiny, unlikely to grow, and a plain string keeps the migration
# and the router free of enum-type juggling.
FINDING_IMAGE_KINDS: tuple[str, ...] = ("figure", "graphical_abstract")


class FindingImage(Base):
    """One author-supplied image attached to a Finding, ordered by `position`."""

    __tablename__ = "finding_images"
    __table_args__ = (
        # Re-uploading identical bytes to the same finding is a no-op, not a
        # second row — the router returns the existing image.
        UniqueConstraint("finding_id", "content_hash", name="uq_finding_image_hash"),
        CheckConstraint(
            "kind IN ('figure', 'graphical_abstract')",
            name="ck_finding_image_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("findings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Who uploaded it. A thread's images can come from collaborators, so this
    # is recorded per row rather than inferred from the finding owner.
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[str | None] = mapped_column(String, nullable=True)
    # Dense per finding (0, 1, 2, ...); renormalized on every insert/delete/
    # reorder so the read order is always unambiguous.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_bucket: Mapped[str] = mapped_column(String, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    # Best-effort pixel dimensions — only filled when an image library is
    # already available; left NULL otherwise (no new dependency for this).
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
