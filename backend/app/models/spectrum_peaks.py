"""Persisted, versioned peak index — the prefilter that keeps matching cheap.

Cosine over a 512-point feature vector is accurate but linear in corpus size.
This table exists so the corpus can be narrowed *before* any vector is touched:
`binned_cm1` holds each spectrum's peak positions quantized to a few cm-1, GIN
indexed, so "which library spectra have a peak near 1085?" is one index scan
instead of a full table read.

Structurally a twin of `SimilarityFeature` (same source-hash + version cache
gate), so a reader who understands one understands the other.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Modality, modality_enum


class SpectrumPeaks(Base):
    """Detected peaks for one immutable spectrum revision."""

    __tablename__ = "spectrum_peaks"
    __table_args__ = (
        # Declared here rather than only in the Alembic revision on purpose:
        # `backend/tests/conftest.py` builds its schema with
        # `Base.metadata.create_all()`, so an index that lives only in the
        # migration is silently absent from every test — and the prefilter
        # would pass its tests while never actually using an index.
        Index(
            "ix_spectrum_peaks_bins_gin",
            "binned_cm1",
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spectrum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("spectra.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    modality: Mapped[Modality] = mapped_column(modality_enum, nullable=False)

    peak_index_version: Mapped[str] = mapped_column(String(40), nullable=False)
    canonicalization_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # The user-facing "main peak": the strongest band in the spectrum. Indexed
    # because the widened prefilter rung orders candidates by how close their
    # main peak sits to the query's.
    primary_peak_cm1: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    primary_peak_prominence: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_to_background: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    peak_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    wavenumber_min: Mapped[float] = mapped_column(Float, nullable=False)
    wavenumber_max: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    noise_sigma: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Full peak objects for display and for counting matched bands.
    peaks: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    # postgresql.ARRAY, not sa.ARRAY: only the dialect type exposes the
    # `.overlap()` comparator that emits `&&` and hits the GIN array_ops index.
    binned_cm1: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, default=list, server_default=text("'{}'")
    )

    qc_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    qc_reasons: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
