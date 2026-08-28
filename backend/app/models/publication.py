import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Publication(Base):
    """A resolver-backed paper record that may group several public spectra."""

    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    doi: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, server_default="crossref")
    verification_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="verified"
    )
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublicationSnapshot(Base):
    """Resolver-backed publication evidence attached to one spectrum.

    A DOI string on its own is only a user claim. This row records the provider
    response and the instant it was checked so a verified label is auditable.
    """

    __tablename__ = "publication_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    spectrum_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=False, unique=True
    )
    doi: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False, server_default="crossref")
    verification_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="verified"
    )
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )