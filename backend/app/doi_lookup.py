"""DOI metadata lookup via Crossref's public API, for auto-populating paper
metadata (title/authors/journal/year) instead of manual entry — per the
architecture doc's Module 3 framing.

Security/reliability boundary: exactly like `app.ingestion.llm_fallback`
treats LLM output, the Crossref HTTP response is untrusted input. It is
*never* passed around as a raw dict — `lookup_doi` parses it strictly into
`DoiMetadata` (via an internal permissive-but-bounded intermediate parse of
Crossref's messy nested shape) and returns `None` (never raises) for
anything that doesn't look like a valid, found work, so callers can turn
that into a clean "not found" response rather than a 500.
"""
from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

CROSSREF_API_BASE = "https://api.crossref.org/works"

# Crossref's "polite pool" just wants a User-Agent identifying the app with
# a contact — this is a placeholder; swap in a real contact before prod.
USER_AGENT = "RamanHub/0.1 (mailto:noreply@example.com)"

REQUEST_TIMEOUT_SECONDS = 5.0


def normalize_doi(value: str) -> str | None:
    """Normalize a user-entered DOI into the durable stored representation."""
    doi = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip().lower()
    if not doi.startswith("10.") or "/" not in doi or any(char.isspace() for char in doi):
        return None
    return doi


class DoiMetadata(BaseModel):
    """Typed, validated shape for DOI-derived paper metadata. Every field
    besides `doi` is optional — Crossref records are frequently missing
    pieces, and a partial record is still useful for the frontend to show
    as a review-before-confirm preview (never auto-trusted/auto-submitted)."""

    doi: str
    title: str | None = None
    authors: list[str] = []
    journal: str | None = None
    year: int | None = None
    url: str | None = None


def _extract_title(message: dict[str, Any]) -> str | None:
    title = message.get("title")
    if isinstance(title, list) and title and isinstance(title[0], str):
        return title[0]
    if isinstance(title, str):
        return title
    return None


def _extract_authors(message: dict[str, Any]) -> list[str]:
    authors_raw = message.get("author")
    if not isinstance(authors_raw, list):
        return []
    names: list[str] = []
    for entry in authors_raw:
        if not isinstance(entry, dict):
            continue
        given = entry.get("given")
        family = entry.get("family")
        parts = [p for p in (given, family) if isinstance(p, str) and p]
        if parts:
            names.append(" ".join(parts))
        elif isinstance(entry.get("name"), str):
            # Some Crossref records (e.g. organizations) use a flat `name`
            # field instead of given/family.
            names.append(entry["name"])
    return names


def _extract_journal(message: dict[str, Any]) -> str | None:
    container_title = message.get("container-title")
    if isinstance(container_title, list) and container_title and isinstance(container_title[0], str):
        return container_title[0]
    if isinstance(container_title, str):
        return container_title
    return None


def _extract_year(message: dict[str, Any]) -> int | None:
    # Crossref's date structure is deeply nested and defensively parsed:
    # {"published": {"date-parts": [[2020, 5, 1]]}} — prefer "published",
    # fall back to "published-print"/"published-online" if absent.
    for key in ("published", "published-print", "published-online", "issued"):
        block = message.get(key)
        if not isinstance(block, dict):
            continue
        date_parts = block.get("date-parts")
        if not isinstance(date_parts, list) or not date_parts:
            continue
        first = date_parts[0]
        if isinstance(first, list) and first and isinstance(first[0], int):
            return first[0]
    return None


def _extract_url(message: dict[str, Any], doi: str) -> str | None:
    url = message.get("URL")
    if isinstance(url, str) and url:
        return url
    return f"https://doi.org/{doi}"


def _parse_crossref_message(doi: str, message: dict[str, Any]) -> DoiMetadata:
    return DoiMetadata(
        doi=doi,
        title=_extract_title(message),
        authors=_extract_authors(message),
        journal=_extract_journal(message),
        year=_extract_year(message),
        url=_extract_url(message, doi),
    )


async def lookup_doi(doi: str) -> DoiMetadata | None:
    """Looks up `doi` against Crossref's public API. Returns `None` (never
    raises) on a 404/not-found, a network error, or a malformed/unexpected
    response shape — callers should treat `None` as "no metadata available"
    and respond accordingly (e.g. a 404 from the wrapping router)."""
    doi = normalize_doi(doi)
    if doi is None:
        return None

    headers = {"User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{CROSSREF_API_BASE}/{doi}", headers=headers)
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None

    try:
        body = response.json()
    except ValueError:
        return None

    if not isinstance(body, dict):
        return None
    message = body.get("message")
    if not isinstance(message, dict):
        return None

    try:
        return _parse_crossref_message(doi, message)
    except (ValidationError, TypeError, ValueError, KeyError, IndexError):
        # Any unexpected shape inside `message` should degrade to "not
        # found" rather than propagate — this is untrusted third-party
        # input, same posture as the LLM-fallback boundary.
        return None
