import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProcessedCache(Base):
    """Cached processed-spectrum output, keyed by hash(raw_file_id + ledger),
    so repeated views don't recompute the same pipeline."""

    __tablename__ = "processed_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    raw_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_files.id"), nullable=False
    )
    ledger_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_ledgers.id"), nullable=False
    )
    storage_bucket: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    compute_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
