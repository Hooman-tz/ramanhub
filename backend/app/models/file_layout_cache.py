from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FileLayoutCache(Base):
    """Remembers how a file *format* is laid out, keyed by a structure
    signature (delimiter, column count, header shape).

    Deliberately separate from `VendorParseCache`, which answers a different
    question under a different key: that table caches the *metadata* template
    of a header, while this one caches where the numbers live. The keys
    genuinely diverge — every headerless export normalizes to the same empty
    header, so a plain two-column file and a ten-trace matrix share a header
    hash while needing completely different layouts.

    A layout the user declared by hand is stored here too, so a format only
    ever has to be explained once.
    """

    __tablename__ = "file_layout_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    structure_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    # A serialized `app.schemas.ingestion.FileLayout`, including its own
    # `source` ("heuristic" | "llm" | "user") and confidence.
    layout: Mapped[dict] = mapped_column(JSONB, nullable=False)
    detector_version: Mapped[str] = mapped_column(String, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
