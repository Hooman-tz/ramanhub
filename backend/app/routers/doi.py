"""Public DOI metadata lookup — auto-populates paper metadata (title/
authors/journal/year) from Crossref instead of manual entry.

Mounted with no prefix — `GET /doi-lookup?doi=...`. Public/no-auth: this is
a read-only metadata lookup against a third-party API, not a write against
our own data, so there's nothing here to scope to a user.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.doi_lookup import DoiMetadata, lookup_doi

router = APIRouter(tags=["doi"])


@router.get("/doi-lookup", response_model=DoiMetadata)
async def get_doi_metadata(
    doi: str = Query(..., min_length=1, description="A DOI, e.g. 10.1021/acs.analchem.xxxxxxx"),
) -> DoiMetadata:
    metadata = await lookup_doi(doi)
    if metadata is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DOI not found")
    return metadata
