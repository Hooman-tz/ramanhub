"""Persisted, versioned Raman search features."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Modality, modality_enum


class SimilarityFeature(Base):
    """A fixed-grid feature vector built from one immutable spectrum revision."""

    __tablename__ = "similarity_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id", ondelete="CASCADE"), unique=True, index=True
    )
    modality: Mapped[Modality] = mapped_column(modality_enum, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(40), nullable=False)
    canonicalization_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    wavenumber_min: Mapped[float] = mapped_column(nullable=False)
    wavenumber_max: Mapped[float] = mapped_column(nullable=False)
    point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    qc_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    qc_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'"))
    vector: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())