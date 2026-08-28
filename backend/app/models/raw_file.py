import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Modality, UploadStatus, modality_enum, upload_status_enum


class RawFile(Base):
    """Immutable raw upload. Never updated/deleted at the app layer."""

    __tablename__ = "raw_files"
    __table_args__ = (
        UniqueConstraint("owner_id", "dedupe_hash", name="uq_raw_file_owner_dedupe_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    modality: Mapped[Modality] = mapped_column(
        modality_enum, default=Modality.raman, server_default=Modality.raman.value
    )
    storage_bucket: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String)
    original_filename: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String, index=True)
    # Populated for direct uploads only. Forks deliberately leave this NULL so
    # the same owner can preserve a separate physical-copy lineage.
    dedupe_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # Logical immutable-object version. For storage providers without native
    # object versioning this is the checksum-derived version identifier.
    storage_version: Mapped[str | None] = mapped_column(String, nullable=True)
    checksum_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    vendor_format: Mapped[str | None] = mapped_column(String, nullable=True)
    upload_status: Mapped[UploadStatus] = mapped_column(
        upload_status_enum, default=UploadStatus.uploaded, server_default=UploadStatus.uploaded.value
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
