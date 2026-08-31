"""ISSN normalization + journal lookup against the SCImago `journals` table.

Used by `POST /v1/findings/{id}/link-doi` to turn the ISSN list Crossref
returns for a paper into a quartile / SJR / cover image, and by
`scripts/import_scimago.py` to normalize ISSNs on the way in so both sides
agree on the stored form.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.journal import Journal

_ISSN_STRIP = re.compile(r"[^0-9X]")


def normalize_issn(value: str | None) -> str | None:
    """`'1234-567X'` / `'1234 567x'` -> `'1234567X'`; anything that is not an
    8-character ISSN once punctuation is removed -> `None`."""
    if not value:
        return None
    cleaned = _ISSN_STRIP.sub("", value.upper())
    return cleaned if len(cleaned) == 8 else None


def match_journal(db: Session, issns: list[str] | None) -> Journal | None:
    """First `Journal` row whose normalized ISSN matches any entry in
    `issns` (also normalized), or `None`."""
    for raw in issns or []:
        norm = normalize_issn(raw)
        if norm is None:
            continue
        journal = db.execute(
            select(Journal).where(Journal.issn == norm)
        ).scalars().first()
        if journal is not None:
            return journal
    return None
