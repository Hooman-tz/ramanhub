"""Download and citation endpoints.

Mounted with no prefix:
`GET /spectra/{id}/download?format=csv|tsv|json|jcamp&stage=processed|raw`
`GET /spectra/{id}/citation?format=bibtex|ris|text`
`GET /findings/{id}/citation?format=bibtex|ris|text`
`GET /findings/{id}/bundle` — a ZIP of everything the finding contains

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

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user_optional
from app.config import settings
from app.db.session import get_db
from app.export import bundle as bundle_mod
from app.export import citation as citation_mod
from app.export import jcampdx, tabular
from app.models.finding import Finding, FindingSpectrum
from app.models.license import License
from app.models.processing_ledger import ProcessingLedger
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_finding_readable, require_owner_or_public
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


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _finding_public_url(finding: Finding) -> str:
    identifier = finding.accession or finding.id
    return f"{settings.FRONTEND_URL.rstrip('/')}/f/{identifier}"


def _finding_citation_subject(
    finding: Finding, db: Session
) -> citation_mod.CitationSubject:
    """Build the citation for a finding.

    Authorship is the thread owner plus every distinct entry author, in
    first-contribution order — a finding is a collaborative object, and
    crediting only the person who opened the thread would misattribute work
    that others added to it.
    """
    owner = db.get(User, finding.owner_id)
    license_row = db.get(License, finding.license_id) if finding.license_id else None
    published = finding.published_at or finding.created_at

    authors: list[str] = []
    orcids: list[str] = []
    seen: set = set()
    for user in [owner, *_entry_authors(finding, db)]:
        if user is None or user.id in seen:
            continue
        seen.add(user.id)
        authors.append(user.display_name or user.handle or "RamanHub contributor")
        if user.orcid_id:
            orcids.append(user.orcid_id)

    return citation_mod.CitationSubject(
        accession=finding.accession,
        title=finding.title,
        authors=authors,
        year=published.year if published else None,
        doi=finding.doi,
        url=_finding_public_url(finding),
        license_name=license_row.name if license_row else None,
        orcids=orcids,
        kind="finding",
    )


def _entry_authors(finding: Finding, db: Session) -> list[User]:
    from app.models.finding import FindingEntry

    rows = db.execute(
        select(FindingEntry.author_id)
        .where(FindingEntry.finding_id == finding.id)
        .order_by(FindingEntry.position)
    ).scalars().all()
    return [db.get(User, author_id) for author_id in dict.fromkeys(rows)]


def _get_readable_finding(finding_id: UUID, user: User | None, db: Session) -> Finding:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_finding_readable(finding, user)
    return finding


@router.get("/findings/{finding_id}/citation")
def get_finding_citation(
    finding_id: UUID,
    fmt: str = Query("bibtex", alias="format", pattern="^(bibtex|ris|text)$"),
    download: bool = Query(False),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Cite a finding — the unit a paper actually references, since it is
    the thing that carries the narrative, the figures and the DOI."""
    finding = _get_readable_finding(finding_id, user, db)
    body = citation_mod.render(_finding_citation_subject(finding, db), fmt)

    headers = {}
    if download:
        stem = finding.accession or str(finding.id)
        headers["Content-Disposition"] = (
            f'attachment; filename="{stem}.{citation_mod.FILE_EXTENSIONS[fmt]}"'
        )
    return PlainTextResponse(body, media_type=citation_mod.MEDIA_TYPES[fmt], headers=headers)


@router.get("/findings/{finding_id}/bundle")
def get_finding_bundle(
    finding_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Download everything in a finding as one ZIP: raw and processed
    arrays per spectrum, the ledger that connects them, a manifest with
    checksums, and a citation.

    Member spectra are each re-checked with `require_owner_or_public`
    rather than trusted because they're attached: a draft that was attached
    while public, or attached by its owner and later un-published, must not
    ride out inside someone else's bundle.
    """
    finding = _get_readable_finding(finding_id, user, db)

    links = db.execute(
        select(FindingSpectrum, Spectrum)
        .join(Spectrum, Spectrum.id == FindingSpectrum.spectrum_id)
        .where(FindingSpectrum.finding_id == finding.id)
        .order_by(FindingSpectrum.position, FindingSpectrum.id)
    ).all()

    members = []
    skipped = 0
    for link, spectrum in links[: bundle_mod.MAX_BUNDLE_SPECTRA]:
        try:
            require_owner_or_public(spectrum, user)
        except HTTPException:
            skipped += 1
            continue

        ledger_steps: list = []
        if spectrum.current_ledger_id is not None:
            ledger_row = db.get(ProcessingLedger, spectrum.current_ledger_id)
            if ledger_row is not None:
                ledger_steps = list(ledger_row.steps or [])

        members.append(
            {
                "id": spectrum.id,
                "accession": spectrum.accession,
                "title": spectrum.title,
                "label": link.label,
                "raw": load_raw_arrays(spectrum, db),
                "processed": load_spectrum_arrays(spectrum, db),
                "ledger": ledger_steps,
                "metadata": build_export_metadata(
                    spectrum, "processed" if ledger_steps else "raw", db
                ),
            }
        )

    if not members:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nothing in this finding is available to download.",
        )

    license_row = db.get(License, finding.license_id) if finding.license_id else None
    payload = bundle_mod.build_bundle(
        accession=finding.accession or str(finding.id),
        title=finding.title,
        subject=_finding_citation_subject(finding, db),
        members=members,
        license_name=license_row.name if license_row else None,
    )

    stem = finding.accession or str(finding.id)
    headers = {"Content-Disposition": f'attachment; filename="{stem}.zip"'}
    if skipped:
        # Surfaced as a header rather than silently trimming the archive —
        # a bundle that quietly contains less than the page showed is worse
        # than one that says so.
        headers["X-RamanHub-Skipped-Spectra"] = str(skipped)

    return Response(payload, media_type="application/zip", headers=headers)
