"""Download and citation endpoints.

Mounted with no prefix:
`GET /spectra/{id}/download?format=csv|tsv|json|jcamp&stage=processed|raw`
`GET /spectra/{id}/citation?format=bibtex|ris|text`

Every route goes through `require_owner_or_public`, the same row-level rule
as every other spectrum read — a download endpoint that skipped it would be
the most direct possible way to exfiltrate someone's draft data.

Text formats stream via `StreamingResponse` over a generator, so a
hyperspectral-sized array is never fully materialized as one string in
memory. JSON does not stream (it's a single document by construction), which
is fine at Raman spectrum sizes and is why `json` is not the default.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_optional
from app.config import settings
from app.db.session import get_db
from app.export import citation as citation_mod
from app.export import jcampdx, tabular
from app.models.license import License
from app.models.processing_ledger import ProcessingLedger
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_owner_or_public
from app.spectrum_access import load_raw_arrays, load_spectrum_arrays

router = APIRouter(tags=["export"])

TABULAR_MEDIA_TYPES = {
    # text/csv would make a browser render it inline; these are downloads.
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "json": "application/json",
    "jcamp": "chemical/x-jcamp-dx",
}
FILE_EXTENSIONS = {"csv": "csv", "tsv": "tsv", "json": "json", "jcamp": "jdx"}


def _get_readable_spectrum(spectrum_id: UUID, user: User | None, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)
    return spectrum


def _public_url(spectrum: Spectrum) -> str:
    """Canonical public URL, preferring the accession — that's the form
    meant to survive in a printed citation."""
    identifier = spectrum.accession or spectrum.id
    return f"{settings.FRONTEND_URL.rstrip('/')}/s/{identifier}"


def _contributor(spectrum: Spectrum, db: Session) -> User | None:
    return db.get(User, spectrum.owner_id)


def build_export_metadata(spectrum: Spectrum, stage: str, db: Session) -> dict:
    """Provenance header shared by every text export format.

    `processing` names the applied steps rather than just saying
    "processed", so a downloaded file records what was actually done to it —
    the ledger is the point of the platform, and an export that dropped it
    would hand someone numbers with no way to know their history.
    """
    owner = _contributor(spectrum, db)
    license_row = db.get(License, spectrum.license_id) if spectrum.license_id else None

    processing = "raw (no processing applied)"
    if stage == "processed" and spectrum.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, spectrum.current_ledger_id)
        if ledger_row is not None and ledger_row.steps:
            processing = " -> ".join(
                f"{step.get('type')}@{step.get('version', '?')}" for step in ledger_row.steps
            )

    metadata = {
        "accession": spectrum.accession,
        "title": spectrum.title,
        "contributor": (owner.display_name or owner.handle) if owner else None,
        "orcid": owner.orcid_id if owner else None,
        "modality": getattr(spectrum.modality, "value", spectrum.modality),
        "material_type": spectrum.material_type,
        "laser_wavelength_nm": spectrum.excitation_wavelength_nm,
        "stage": stage,
        "processing": processing,
        "license": license_row.name if license_row else None,
        "doi": spectrum.doi,
        "url": _public_url(spectrum),
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "RamanHub",
    }
    return {k: v for k, v in metadata.items() if v is not None}


def _citation_subject(spectrum: Spectrum, db: Session) -> citation_mod.CitationSubject:
    owner = _contributor(spectrum, db)
    license_row = db.get(License, spectrum.license_id) if spectrum.license_id else None
    published = spectrum.published_at or spectrum.created_at

    authors = []
    orcids = []
    if owner is not None:
        authors.append(owner.display_name or owner.handle or "RamanHub contributor")
        if owner.orcid_id:
            orcids.append(owner.orcid_id)

    return citation_mod.CitationSubject(
        accession=spectrum.accession,
        title=spectrum.title,
        authors=authors,
        year=published.year if published else None,
        doi=spectrum.doi,
        url=_public_url(spectrum),
        license_name=license_row.name if license_row else None,
        orcids=orcids,
        kind="spectrum",
    )


@router.get("/spectra/{spectrum_id}/download")
def download_spectrum(
    spectrum_id: UUID,
    fmt: str = Query("csv", alias="format", pattern="^(csv|tsv|json|jcamp)$"),
    stage: str = Query("processed", pattern="^(processed|raw)$"),
    include_header_comment: bool = Query(
        True,
        description="Prefix CSV/TSV with '# key: value' provenance lines. Turn off for tools "
        "that can't skip comment lines.",
    ),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Download a spectrum's arrays.

    `stage=processed` (the default) returns the spectrum as currently
    displayed — the ledger applied. `stage=raw` returns the untouched
    original, which is what anyone reproducing the analysis from scratch
    needs.
    """
    spectrum = _get_readable_spectrum(spectrum_id, user, db)

    if stage == "raw":
        wavenumbers, intensities = load_raw_arrays(spectrum, db)
        effective_stage = "raw"
    else:
        wavenumbers, intensities = load_spectrum_arrays(spectrum, db)
        effective_stage = "processed" if spectrum.current_ledger_id else "raw"

    metadata = build_export_metadata(spectrum, effective_stage, db)
    stem = spectrum.accession or str(spectrum.id)
    filename = f"{stem}_{effective_stage}.{FILE_EXTENSIONS[fmt]}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

    if fmt == "json":
        return PlainTextResponse(
            tabular.to_json(wavenumbers, intensities, metadata),
            media_type=TABULAR_MEDIA_TYPES[fmt],
            headers=headers,
        )

    if fmt == "jcamp":
        generator = jcampdx.to_jcampdx(
            wavenumbers,
            intensities,
            title=spectrum.title or stem,
            metadata=metadata,
        )
    else:
        generator = tabular.to_delimited(
            wavenumbers,
            intensities,
            fmt=fmt,
            metadata=metadata,
            include_header_comment=include_header_comment,
        )

    return StreamingResponse(
        generator, media_type=TABULAR_MEDIA_TYPES[fmt], headers=headers
    )


@router.get("/spectra/{spectrum_id}/citation")
def get_spectrum_citation(
    spectrum_id: UUID,
    fmt: str = Query("bibtex", alias="format", pattern="^(bibtex|ris|text)$"),
    download: bool = Query(False, description="Send as a file attachment rather than inline."),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Cite this spectrum. Inline by default so the UI can show a
    copy-to-clipboard block without triggering a download."""
    spectrum = _get_readable_spectrum(spectrum_id, user, db)
    subject = _citation_subject(spectrum, db)
    body = citation_mod.render(subject, fmt)

    headers = {}
    if download:
        stem = spectrum.accession or str(spectrum.id)
        extension = citation_mod.FILE_EXTENSIONS[fmt]
        headers["Content-Disposition"] = f'attachment; filename="{stem}.{extension}"'

    return PlainTextResponse(
        body, media_type=citation_mod.MEDIA_TYPES[fmt], headers=headers
    )
