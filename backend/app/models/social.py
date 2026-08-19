"""Module 4's social layer: upvotes and comments on published spectra.

Deliberately quarantined from core search/discovery — nothing here ever
feeds spectra ranking in app.routers.search; it only powers the separate
Trending feed (app.routers.trending).
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Vote(Base):
    """One upvote from one user on one spectrum. Presence of a row IS the
    vote (no direction/value column) — voting again removes it (toggle),
    handled at the router layer."""

    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("spectrum_id", "user_id", name="uq_vote_spectrum_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id = mapped_column(UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=False, index=True)
    user_id = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id = mapped_column(UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=False, index=True)
    user_id = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
