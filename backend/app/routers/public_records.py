"""Public spectrum records, citation payloads, and safe share redirects."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.community import canonical_url, public_author
from app.config import settings
from app.db.session import get_db
from app.models.license import License
from app.models.publication import Publication
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import effective_state, require_owner_or_public
from app.spectrum_lifecycle import publication_for_spectrum, spectrum_provenance

router = APIRouter(tags=["public-records"])


class PublicSpectrumRecord(BaseModel):
    id: UUID
    title: str | None
    description: str | None
    modality: str
    state: str
    metadata: dict | None
    quality_flags: dict | None
    published_at: object | None
    author: dict
    license: dict | None
    provenance: dict
    publication: dict | None
    canonical_path: str
    canonical_url: str | None
    citation_url: str
    download_url: str


def _visible_spectrum_or_404(spectrum_id: UUID, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, None)
    return spectrum


def _citation_text(spectrum: Spectrum, author: dict, publication: Publication | None) -> str:
    snapshot = publication.snapshot if publication is not None else {}
    paper_title = snapshot.get("title") or spectrum.title or "Untitled spectrum"
    year = snapshot.get("year") or (spectrum.published_at.year if spectrum.published_at else "n.d.")
    doi = publication.doi if publication is not None else spectrum.doi
    doi_part = f" https://doi.org/{doi}" if doi else ""
    return (
        f"{author['display_name']} ({year}). {paper_title}. "
        f"Spectra Insight public spectrum {spectrum.id}.{doi_part}"
    )


def _record_payload(spectrum: Spectrum, db: Session) -> PublicSpectrumRecord:
    owner = db.get(User, spectrum.owner_id)
    author = public_author(owner)
    license_row = db.get(License, spectrum.license_id) if spectrum.license_id else None
    publication = db.get(Publication, spectrum.publication_id) if spectrum.publication_id else None
    snapshot = publication_for_spectrum(spectrum.id, db)
    path = f"/spectra/{spectrum.id}"
    return PublicSpectrumRecord(
        id=spectrum.id,
        title=spectrum.title,
        description=spectrum.description,
        modality=spectrum.modality.value,
        state=effective_state(spectrum),
        metadata=spectrum.confirmed_metadata,
        quality_flags=spectrum.quality_flags,
        published_at=spectrum.published_at,
        author=author,
        license=(
            {"id": license_row.id, "name": license_row.name, "url": license_row.url}
            if license_row is not None
            else None
        ),
        provenance=spectrum_provenance(spectrum, db),
        publication=(
            {
                "id": str(publication.id),
                "doi": publication.doi,
                "provider": publication.provider,
                "verification_status": publication.verification_status,
                "snapshot": publication.snapshot,
                "verified_at": publication.verified_at,
            }
            if publication is not None
            else (
                {
                    "doi": snapshot.doi,
                    "provider": snapshot.provider,
                    "verification_status": snapshot.verification_status,
                    "snapshot": snapshot.snapshot,
                    "verified_at": snapshot.verified_at,
                }
                if snapshot is not None
                else None
            )
        ),
        canonical_path=path,
        canonical_url=canonical_url(path),
        citation_url=f"/public/spectra/{spectrum.id}/citation",
        download_url=f"/spectra/{spectrum.id}/data",
    )


@router.get("/public/spectra/{spectrum_id}", response_model=PublicSpectrumRecord)
def get_public_spectrum_record(
    spectrum_id: UUID, db: Session = Depends(get_db)
) -> PublicSpectrumRecord:
    return _record_payload(_visible_spectrum_or_404(spectrum_id, db), db)


@router.get("/public/spectra/{spectrum_id}/citation")
def get_public_spectrum_citation(
    spectrum_id: UUID,
    format: str = Query(default="text", pattern="^(text|bibtex)$"),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    spectrum = _visible_spectrum_or_404(spectrum_id, db)
    owner = db.get(User, spectrum.owner_id)
    author = public_author(owner)
    publication = db.get(Publication, spectrum.publication_id) if spectrum.publication_id else None
    if format == "bibtex":
        citation_key = f"spectra_insight_{str(spectrum.id).replace('-', '')[:12]}"
        text = (
            f"@misc{{{citation_key},\n"
            f"  author = {{{author['display_name']}}},\n"
            f"  title = {{{spectrum.title or 'Untitled spectrum'}}},\n"
            f"  howpublished = {{Spectra Insight}},\n"
            f"  note = {{https://spectra-in.site/spectra/{spectrum.id}}},\n"
            f"}}"
        )
    else:
        text = _citation_text(spectrum, author, publication)
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/public/spectra/{spectrum_id}/share-preview")
def get_share_preview(spectrum_id: UUID, db: Session = Depends(get_db)) -> dict:
    record = _record_payload(_visible_spectrum_or_404(spectrum_id, db), db)
    return {
        "title": record.title or "Spectrum on Spectra Insight",
        "description": record.description or f"Public {record.modality} spectrum",
        "canonical_path": record.canonical_path,
        "canonical_url": record.canonical_url,
        "author": record.author["display_name"],
    }


@router.get("/s/{spectrum_id}", include_in_schema=False)
def redirect_short_public_spectrum(
    spectrum_id: UUID, db: Session = Depends(get_db)
) -> RedirectResponse:
    _visible_spectrum_or_404(spectrum_id, db)
    path = f"/spectra/{spectrum_id}"
    return RedirectResponse(url=canonical_url(path) or f"{settings.FRONTEND_URL.rstrip('/')}{path}")