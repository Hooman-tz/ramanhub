from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Modality, ParseSource, modality_enum, parse_source_enum


class VendorParseCache(Base):
    """Caches successful (deterministic or LLM-derived) header parse templates,
    keyed by a hash of the raw header structure, so the same instrument/
    software-version signature is never re-parsed twice."""

    __tablename__ = "vendor_parse_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    header_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    modality: Mapped[Modality] = mapped_column(modality_enum)
    vendor_format: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_version: Mapped[str] = mapped_column(String)
    source: Mapped[ParseSource] = mapped_column(parse_source_enum)
    parsed_template: Mapped[dict] = mapped_column(JSONB)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
