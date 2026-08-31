"""SCImago-ranked journals, keyed by ISSN.

Populated by `scripts/import_scimago.py` from the public SCImago Journal Rank
CSV. One row per ISSN — SCImago lists a journal's print and electronic ISSNs
together on one line, and a DOI's Crossref record may cite either — so the
same journal can appear as two rows differing only by `issn`, and a lookup by
whichever ISSN Crossref returned still resolves it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Journal(Base):
    __tablename__ = "journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Normalized: 8 chars, no dash, uppercase (the trailing check digit can be 'X').
    issn: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    issn_l: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    sjr: Mapped[float | None] = mapped_column(Float, nullable=True)
    quartile: Mapped[str | None] = mapped_column(String(2), nullable=True)
    h_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    sjr_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="scimago", server_default="scimago"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
