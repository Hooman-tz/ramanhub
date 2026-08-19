import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Modality, modality_enum


class ProcessingLedger(Base):
    """Immutable, replayable record of the exact processing steps (+versioned
    algorithm/params) applied to a raw file. Never mutated once created."""

    __tablename__ = "processing_ledgers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    raw_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_files.id"), nullable=False
    )
    modality: Mapped[Modality] = mapped_column(modality_enum)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    steps: Mapped[dict] = mapped_column(JSONB)
    ledger_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    derived_from_routine_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_routines.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
