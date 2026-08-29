import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Modality, SpectrumState, modality_enum, spectrum_state_enum


class Spectrum(Base):
    """A published/draft spectrum entry, referencing an immutable raw file and
    (optionally) the processing ledger currently applied for display."""

    __tablename__ = "spectra"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    raw_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_files.id"), nullable=False, unique=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Human-quotable public identifier (RH-S-000042). Assigned from
    # spectrum_accession_seq at publish time; see app.models.accession. The
    # spectra.py router wires this in fully in a follow-up — for now new
    # spectra may carry a NULL accession, which the feed renders as absent.
    accession: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True, index=True
    )
    modality: Mapped[Modality] = mapped_column(modality_enum)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    quality_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    canonicalization_version: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_spectrum_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=True, index=True
    )
    # Denormalized, indexed search fields (Module 4) — populated from
    # confirmed_metadata / a computed SNR at spectrum-update time (see
    # app.spectra_io.compute_snr and app.routers.spectra), rather than
    # queried out of JSONB on every search request.
    material_type: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    excitation_wavelength_nm: Mapped[float | None] = mapped_column(Numeric, nullable=True, index=True)
    snr: Mapped[float | None] = mapped_column(Numeric, nullable=True, index=True)
    current_ledger_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_ledgers.id"), nullable=True
    )
    license_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("licenses.id"), nullable=True
    )
    state: Mapped[SpectrumState] = mapped_column(
        spectrum_state_enum, default=SpectrumState.draft, server_default=SpectrumState.draft.value
    )
    embargo_release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    doi: Mapped[str | None] = mapped_column(String, nullable=True)
    publication_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publications.id"), nullable=True, index=True
    )
    moderation_status: Mapped[str] = mapped_column(
        String, nullable=False, default="visible", server_default=text("'visible'")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
