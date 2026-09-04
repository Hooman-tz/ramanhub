"""The public reference library: named compounds a spectrum can be identified against.

A reference is *not* a separate kind of spectrum. It is an ordinary published
`Spectrum` plus the catalogue metadata that makes it an identity claim — a
compound name, a formula, a provenance URL. Keeping it that way means bundled
imports (RRUFF) and user contributions travel the same ingestion, storage,
canonicalization and similarity-indexing path, and the matcher never has to
care which one it is looking at.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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
from app.models.enums import (
    ReferenceCurationStatus,
    ReferenceTrustTier,
    reference_curation_status_enum,
    reference_trust_tier_enum,
)


class ReferenceEntry(Base):
    """One identified compound in the public reference library."""

    __tablename__ = "reference_entries"
    __table_args__ = (
        # Nullable `source_id` is deliberate and load-bearing: Postgres treats
        # NULLs as distinct, so user submissions (which have no upstream id)
        # are unconstrained while a re-run of the RRUFF import collides on
        # every row it already created. That gives the seeder idempotency for
        # free, without a pre-flight SELECT per record.
        UniqueConstraint("source", "source_id", name="uq_reference_source_id"),
        Index("ix_reference_entries_source", "source", "source_dataset"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    spectrum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("spectra.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # --- identity -------------------------------------------------------
    compound_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    # Synonyms, so "calcite" and "calcium carbonate" both find the same entry.
    common_names: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'")
    )
    chemical_formula: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    cas_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    mineral_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # --- provenance -----------------------------------------------------
    # Plain varchar rather than an enum, matching the reasoning on
    # `AnalysisDataset.color`: the set of sources will grow (rruff -> user ->
    # curated -> nist -> a RamanBench subset) and extending a Postgres enum
    # costs a migration every time. Pydantic enforces the allowed values at
    # the edge, which is where a bad value would actually arrive.
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_dataset: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provenance_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- trust ----------------------------------------------------------
    trust_tier: Mapped[ReferenceTrustTier] = mapped_column(
        reference_trust_tier_enum, nullable=False, index=True
    )
    curation_status: Mapped[ReferenceCurationStatus] = mapped_column(
        reference_curation_status_enum,
        nullable=False,
        index=True,
        default=ReferenceCurationStatus.approved,
        server_default=text("'approved'"),
    )
    flagged_for_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"), index=True
    )
    report_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    contributed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    curated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    curated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
