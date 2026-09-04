import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
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
from app.models.enums import IngestionStatus, ingestion_status_enum


class IngestionJob(Base):
    """Async job that parses a raw file's vendor header into structured metadata."""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        UniqueConstraint("raw_file_id", name="uq_ingestion_job_raw_file"),
    )

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
    parser_version: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    canonicalization_version: Mapped[str | None] = mapped_column(String, nullable=True)
    header_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    extracted_metadata_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sanity_check_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extracted_metadata_confirmed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # How to read numbers out of this file: a serialized
    # `app.schemas.ingestion.FileLayout`. NULL means detection has not run or
    # could not resolve it (see `status == needs_input`), in which case array
    # loading falls back to the historical two-column assumption.
    file_layout: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # A serialized `PreviewGrid`, kept so the UI can show the user the actual
    # cells when asking them to declare a layout by hand.
    structure_preview: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Which rung of the detection ladder answered: cache | heuristic | llm |
    # llm-wide | user | unresolved. Provenance, same as `parser_used`.
    layout_source: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The FIRST draft created from this file. Not unique any more: a
    # multi-spectrum file yields one draft per trace, and they are grouped by
    # `draft_dataset_id`. This column stays as the "open this upload" target.
    draft_spectrum_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("spectra.id"), nullable=True, index=True
    )
    # Set only when a file produced more than one draft.
    draft_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_datasets.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
