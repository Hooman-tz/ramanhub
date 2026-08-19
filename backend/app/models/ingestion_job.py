import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import IngestionStatus, ingestion_status_enum


class IngestionJob(Base):
    """Async job that parses a raw file's vendor header into structured metadata."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    raw_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_files.id"), nullable=False
    )
    status: Mapped[IngestionStatus] = mapped_column(
        ingestion_status_enum,
        default=IngestionStatus.pending,
        server_default=IngestionStatus.pending.value,
    )
    parser_used: Mapped[str | None] = mapped_column(String, nullable=True)
    header_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_metadata_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sanity_check_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extracted_metadata_confirmed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
