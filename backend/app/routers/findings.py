"""Findings: create, edit, append entries, attach spectra, publish.

Mounted at `/v1`. The thread model is described in `app.models.finding`;
this router is the write path for it.

Two rules run through everything here:

1. **Publishing a Finding with spectra requires those spectra to be
   published.** A public write-up whose figures point at private data
   renders as a wall of 404s. Enforced in `_assert_publishable`. A
   *note-only* Finding — no attached spectra and no figure/analysis
   entries — is a plain discussion post and may publish freely; that is the
   low-friction "post to the feed" path.

2. **Entries are append-only in spirit.** Editing an entry's prose is fine;
   the ordering is stable and new results arrive as new entries, so a reader
   who saw the thread yesterday sees additions rather than a silently
   rewritten argument.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import idempotency
from app.analysis.engine import load_spectrum_arrays
from app.auth.deps import get_current_full_user, get_current_user, get_current_user_optional
from app.config import settings
from app.db.session import get_db
from app.doi_lookup import lookup_doi
from app.enrichment import EnrichmentError, summarize_abstract
from app.journals import match_journal
from app.llm import llm_configured
from app.models.accession import next_finding_accession
from app.models.enums import FindingEntryKind, FindingState, SpectrumState
from app.models.finding import Finding, FindingEntry, FindingSpectrum
from app.models.finding_image import FINDING_IMAGE_KINDS, FindingImage
from app.models.social import Comment, Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.overlay import compute_overlay
from app.processing.state_machine import require_finding_readable, require_owner_or_public
from app.storage.s3_client import download_bytes, object_exists, upload_bytes

router = APIRouter(prefix="/v1", tags=["findings"])

MAX_TAGS = 10
MAX_TAG_LENGTH = 40
MAX_SPECTRA_PER_FINDING = 200
MAX_IMAGES_PER_FINDING = 12
# Figures are raster images, not datasets — a much tighter cap than the
# raw-spectrum `MAX_UPLOAD_SIZE_MB`.
MAX_IMAGE_BYTES = 8 * 1024 * 1024
# Accepted image upload types -> the extension used in the storage key.
IMAGE_CONTENT_TYPE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _sniff_image_type(raw: bytes) -> str | None:
    """Leading magic bytes -> content-type, independent of the client's
    declared `Content-Type`. Returns None if the bytes match nothing we accept."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


# --------------------------------------------------------------- schemas


# A link to the code/analysis repo behind a finding. Not verified — just
# bounded and required to look like a URL so it renders as a link. An empty
# string is allowed and clears the field (same ergonomics as `doi`).
REPO_URL_FIELD = Field(default=None, max_length=2048, pattern=r"^(https?://|$)")


class FindingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    abstract_md: str | None = Field(default=None, max_length=20_000)
    tags: list[str] | None = None
    repo_url: str | None = REPO_URL_FIELD


class FindingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    abstract_md: str | None = Field(default=None, max_length=20_000)
    tags: list[str] | None = None
    doi: str | None = None
    repo_url: str | None = REPO_URL_FIELD


class FindingPublish(BaseModel):
    license_id: str


class LinkDoi(BaseModel):
    doi: str = Field(default="", max_length=200)


class EntryCreate(BaseModel):
    kind: FindingEntryKind
    body_md: str | None = Field(default=None, max_length=20_000)
    config: dict | None = None


class EntryUpdate(BaseModel):
    body_md: str | None = Field(default=None, max_length=20_000)
    config: dict | None = None


class EntryReorder(BaseModel):
    entry_ids: list[UUID]


class ImageUpdate(BaseModel):
    caption: str | None = Field(default=None, max_length=2_000)
    position: int | None = Field(default=None, ge=0)


class ImageReorder(BaseModel):
    image_ids: list[UUID]


class AttachSpectrum(BaseModel):
    spectrum_id: UUID
    label: str | None = Field(default=None, max_length=120)


class EntryOut(BaseModel):
    id: UUID
    author_id: UUID
    position: int
    kind: str
    body_md: str | None
    config: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemberSpectrumOut(BaseModel):
    spectrum_id: UUID
    accession: str | None
    title: str | None
    label: str | None
    position: int
    state: str


class FindingImageOut(BaseModel):
    id: UUID
    kind: str
    caption: str | None
    position: int
    content_type: str
    url: str
    created_at: datetime


class FindingOut(BaseModel):
    id: UUID
    accession: str | None
    owner_id: UUID
    owner_handle: str | None = None
    owner_display_name: str | None = None
    owner_orcid: str | None = None
    title: str
    abstract_md: str | None
    state: str
    license_id: str | None
    doi: str | None
    repo_url: str | None
    publication_metadata: dict | None
    tags: list | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    entries: list[EntryOut] = []
    spectra: list[MemberSpectrumOut] = []
    images: list[FindingImageOut] = []
    vote_count: int = 0
    comment_count: int = 0


class OverlayMemberOut(BaseModel):
    spectrum_id: UUID
    label: str | None = None


class FindingOverlayResponse(BaseModel):
    grid_wavenumbers: list[float]
    mean: list[float]
    std: list[float]
    n: int
    members: list[OverlayMemberOut]


class EnrichResponse(BaseModel):
    enriched: bool
    reason: str | None = None
    ai_summary: dict | None = None


# --------------------------------------------------------------- helpers


def _normalize_tags(tags: list[str] | None) -> list[str] | None:
    """Lowercase, de-duplicate, drop blanks, cap count and length.

    Tags are user-supplied free text rendered into the browse UI, so
    bounding them here keeps one user from creating a 500-tag Finding that
    breaks every feed card's layout.
    """
    if tags is None:
        return None
    seen, cleaned = set(), []
    for tag in tags:
        normalized = tag.strip().lower()[:MAX_TAG_LENGTH]
        if normalized and normalized not in seen:
            seen.add(normalized)
            cleaned.append(normalized)
        if len(cleaned) >= MAX_TAGS:
            break
    return cleaned


def _get_finding_for_owner(finding_id: UUID, user: User, db: Session) -> Finding:
    finding = db.get(Finding, finding_id)
    # 404 rather than 403 for someone else's Finding, matching the rest of
    # the codebase: a non-owner must not learn that it exists.
    if finding is None or finding.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return finding


def _members(finding_id: UUID, db: Session) -> list[tuple[FindingSpectrum, Spectrum]]:
    rows = db.execute(
        select(FindingSpectrum, Spectrum)
        .join(Spectrum, Spectrum.id == FindingSpectrum.spectrum_id)
        .where(FindingSpectrum.finding_id == finding_id)
        .order_by(FindingSpectrum.position, FindingSpectrum.id)
    ).all()
    return [(link, spectrum) for link, spectrum in rows]


def _images(finding_id: UUID, db: Session) -> list[FindingImage]:
    return list(
        db.execute(
            select(FindingImage)
            .where(FindingImage.finding_id == finding_id)
            .order_by(FindingImage.position, FindingImage.created_at)
        )
        .scalars()
        .all()
    )


def _serialize_image(image: FindingImage) -> FindingImageOut:
    return FindingImageOut(
        id=image.id,
        kind=image.kind,
        caption=image.caption,
        position=image.position,
        content_type=image.content_type,
        # The portable read path: the bytes live in the owner's object store,
        # streamed back (with the same read gate as the finding) by the route
        # below rather than exposed as a raw storage URL.
        url=f"/v1/findings/{image.finding_id}/images/{image.id}/file",
        created_at=image.created_at,
    )


def _renormalize_image_positions(finding_id: UUID, db: Session) -> None:
    """Rewrite positions to a dense 0..n-1 sequence in current sort order."""
    for position, image in enumerate(_images(finding_id, db)):
        if image.position != position:
            image.position = position
            db.add(image)


def serialize_finding(finding: Finding, db: Session, include_body: bool = True) -> FindingOut:
    owner = db.get(User, finding.owner_id)
    out = FindingOut(
        id=finding.id,
        accession=finding.accession,
        owner_id=finding.owner_id,
        owner_handle=owner.profile_handle if owner else None,
        owner_display_name=owner.display_name if owner else None,
        owner_orcid=owner.orcid_id if owner else None,
        title=finding.title,
        abstract_md=finding.abstract_md,
        state=finding.state.value if hasattr(finding.state, "value") else finding.state,
        license_id=finding.license_id,
        doi=finding.doi,
        repo_url=finding.repo_url,
        publication_metadata=finding.publication_metadata,
        tags=finding.tags,
        published_at=finding.published_at,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )

    if include_body:
        entries = (
            db.execute(
                select(FindingEntry)
                .where(FindingEntry.finding_id == finding.id)
                .order_by(FindingEntry.position, FindingEntry.created_at)
            )
            .scalars()
            .all()
        )
        out.entries = [EntryOut.model_validate(e) for e in entries]

        out.spectra = [
            MemberSpectrumOut(
                spectrum_id=spectrum.id,
                accession=spectrum.accession,
                title=spectrum.title,
                label=link.label,
                position=link.position,
                state=spectrum.state.value if hasattr(spectrum.state, "value") else spectrum.state,
            )
            for link, spectrum in _members(finding.id, db)
        ]

        out.images = [_serialize_image(image) for image in _images(finding.id, db)]

    out.vote_count = int(
        db.execute(select(func.count(Vote.id)).where(Vote.finding_id == finding.id)).scalar_one()
    )
    out.comment_count = int(
        db.execute(
            select(func.count(Comment.id)).where(Comment.finding_id == finding.id)
        ).scalar_one()
    )
    return out


def _has_substantive_entries(finding_id: UUID, db: Session) -> bool:
    """True if the thread has any entry that is more than a plain note — a
    figure, spectra list, peaks/PCA/HCA run, or attachment. Those all render
    from spectrum data, so publishing with them present still requires the
    spectra to be public."""
    kind = db.execute(
        select(FindingEntry.kind)
        .where(
            FindingEntry.finding_id == finding_id,
            FindingEntry.kind != FindingEntryKind.note,
        )
        .limit(1)
    ).first()
    return kind is not None


def _assert_publishable(finding: Finding, db: Session) -> None:
    """A Finding may only go public if everything it *shows* is public.

    A note-only thread (no member spectra, no figure/analysis entries) is a
    plain discussion post — nothing to render from private data — so it
    publishes with no spectrum gate. Anything richer must have every member
    spectrum published first, otherwise the write-up renders as broken
    figures for every reader but the author.
    """
    members = _members(finding.id, db)
    if not members:
        if _has_substantive_entries(finding.id, db):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Attach the spectra this finding's figures use before publishing.",
            )
        return  # note-only: fine to publish
    private = [
        spectrum.accession or str(spectrum.id)
        for _link, spectrum in members
        if spectrum.state != SpectrumState.published
    ]
    if private:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Publish these spectra first, or remove them — a public finding can't "
                f"reference private data: {', '.join(private)}"
            ),
        )


# ---------------------------------------------------------------- routes


@router.post("/findings", response_model=FindingOut, status_code=status.HTTP_201_CREATED)
def create_finding(
    body: FindingCreate,
    request: Request,
    db: Session = Depends(get_db),
    # Guests may draft a Finding, same try-before-login rule as uploading.
    # Publishing is what requires a real account.
    user: User = Depends(get_current_user),
):
    # A retried/replayed POST (slow backend + proxy retry or HTTP/2 reset)
    # carries the same client `Idempotency-Key` — return the first run's
    # response instead of creating a second draft. No header -> None.
    hit = idempotency.check(db, user.id, request)
    if hit is not None:
        return JSONResponse(hit["body"], status_code=hit["status"])

    finding = Finding(
        accession=next_finding_accession(db),
        owner_id=user.id,
        title=body.title,
        abstract_md=body.abstract_md,
        tags=_normalize_tags(body.tags),
        repo_url=body.repo_url,
        state=FindingState.draft,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    result = serialize_finding(finding, db)
    idempotency.record(db, user.id, request, status.HTTP_201_CREATED, result)
    return result


@router.get("/findings", response_model=list[FindingOut])
def list_my_findings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[FindingOut]:
    """The caller's own Findings, in any state — the personal workspace
    view. Public discovery goes through `/v1/feed` and `/search`."""
    findings = (
        db.execute(
            select(Finding)
            .where(Finding.owner_id == user.id)
            .order_by(Finding.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    return [serialize_finding(f, db, include_body=False) for f in findings]


@router.get("/findings/{finding_id}", response_model=FindingOut)
def get_finding(
    finding_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> FindingOut:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_finding_readable(finding, user)
    return serialize_finding(finding, db)


@router.patch("/findings/{finding_id}", response_model=FindingOut)
def update_finding(
    finding_id: UUID,
    body: FindingUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    finding = _get_finding_for_owner(finding_id, user, db)
    if body.title is not None:
        finding.title = body.title
    if body.abstract_md is not None:
        finding.abstract_md = body.abstract_md
    if body.tags is not None:
        finding.tags = _normalize_tags(body.tags)
    if body.doi is not None:
        finding.doi = body.doi or None
    if body.repo_url is not None:
        finding.repo_url = body.repo_url or None
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.post("/findings/{finding_id}/link-doi", response_model=FindingOut)
async def link_doi(
    finding_id: UUID,
    body: LinkDoi,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    """Attach a published paper and cache its Crossref metadata.

    The lookup is done here, at link time, rather than on every read: a feed
    of twenty findings would otherwise make twenty outbound HTTP calls to
    render, and Crossref is neither fast enough nor ours to lean on that
    way. `publication_metadata` is the cache.

    A DOI that Crossref can't resolve is still stored, with a flag saying so.
    Refusing it would block legitimate cases — a brand-new DOI not yet
    indexed, or a registrant Crossref doesn't cover — and the trust tier
    only claims "a DOI is attached", not "we verified the paper exists".
    """
    finding = _get_finding_for_owner(finding_id, user, db)

    doi = body.doi.strip()
    if not doi:
        finding.doi = None
        finding.publication_metadata = None
    else:
        finding.doi = doi
        metadata = await lookup_doi(doi)
        if metadata is None:
            finding.publication_metadata = {"doi": doi, "resolved": False}
        else:
            journal = match_journal(db, metadata.issn)
            pub: dict = {
                "doi": metadata.doi,
                "title": metadata.title,
                "authors": metadata.authors,
                "journal": metadata.journal,
                "issn": metadata.issn,
                "year": metadata.year,
                "url": metadata.url,
                "resolved": True,
                "citations": metadata.citations,
                "quartile": journal.quartile if journal else None,
                "sjr": journal.sjr if journal else None,
                "cover_url": journal.cover_url if journal else None,
                "abstract_raw": metadata.abstract,
            }
            # Enrich inline only when there's an abstract AND a configured key
            # (empty locally / in tests). A failed enrichment is non-fatal —
            # the DOI link still succeeds.
            if metadata.abstract and llm_configured():
                try:
                    summary = await summarize_abstract(metadata.abstract)
                    pub["ai_summary"] = summary.model_dump()
                except EnrichmentError:
                    pass
            finding.publication_metadata = pub

    db.add(finding)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.get("/findings/{finding_id}/overlay", response_model=FindingOverlayResponse)
def finding_overlay(
    finding_id: UUID,
    grid: int = Query(512, ge=16, le=2048),
    max_points: int = Query(2000, gt=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> FindingOverlayResponse:
    """Mean curve + per-point standard-deviation band across a finding's
    member spectra, computed live (like every spectrum-derived read).

    Members the viewer can't see (someone else's draft) are silently
    excluded — same visibility gate as `GET /spectra/{id}/data`.
    """
    finding = db.get(Finding, finding_id)
    require_finding_readable(finding, user)

    arrays: list[tuple] = []
    members: list[OverlayMemberOut] = []
    for link, spectrum in _members(finding.id, db):
        try:
            require_owner_or_public(spectrum, user)
        except HTTPException:
            continue
        wavenumbers, intensities = load_spectrum_arrays(spectrum, db)
        if wavenumbers.size == 0:
            continue
        arrays.append((wavenumbers, intensities))
        members.append(OverlayMemberOut(spectrum_id=spectrum.id, label=link.label))

    grid_wavenumbers, mean, std = compute_overlay(arrays, grid_points=grid, max_points=max_points)
    return FindingOverlayResponse(
        grid_wavenumbers=[float(v) for v in grid_wavenumbers],
        mean=[float(v) for v in mean],
        std=[float(v) for v in std],
        n=len(arrays),
        members=members,
    )


@router.post("/findings/{finding_id}/enrich", response_model=EnrichResponse)
async def enrich_finding(
    finding_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> EnrichResponse:
    """Owner-only. Summarize the linked paper's abstract into
    `publication_metadata.ai_summary`. A no-op (200, `enriched=false`) when
    no LLM key is configured, so the frontend can always call it."""
    finding = _get_finding_for_owner(finding_id, user, db)
    if not llm_configured():
        return EnrichResponse(enriched=False, reason="llm_not_configured")

    pub = dict(finding.publication_metadata or {})
    abstract_raw = pub.get("abstract_raw")
    if not abstract_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This finding has no linked-paper abstract to summarize.",
        )
    try:
        summary = await summarize_abstract(abstract_raw)
    except EnrichmentError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    pub["ai_summary"] = summary.model_dump()
    finding.publication_metadata = pub
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return EnrichResponse(enriched=True, ai_summary=pub["ai_summary"])


@router.delete("/findings/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_finding(
    finding_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    finding = _get_finding_for_owner(finding_id, user, db)
    if finding.state == FindingState.published:
        # Published records are citable. Retracting one is a real editorial
        # action with its own semantics (a tombstone, not a hole), so it is
        # deliberately not a DELETE — see the retraction note in the README.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Published findings can't be deleted, because others may already cite them.",
        )
    db.delete(finding)
    db.commit()


@router.post("/findings/{finding_id}/publish", response_model=FindingOut)
def publish_finding(
    finding_id: UUID,
    body: FindingPublish,
    db: Session = Depends(get_db),
    # Publishing is identity-carrying, so a guest session can't do it.
    user: User = Depends(get_current_full_user),
) -> FindingOut:
    finding = _get_finding_for_owner(finding_id, user, db)
    if finding.state == FindingState.published:
        raise HTTPException(status_code=400, detail="Already published")
    if not body.license_id:
        raise HTTPException(status_code=422, detail="license_id is required to publish")
    _assert_publishable(finding, db)

    finding.license_id = body.license_id
    finding.state = FindingState.published
    finding.published_at = datetime.now(UTC)
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


# --- member spectra ------------------------------------------------------


@router.post(
    "/findings/{finding_id}/spectra",
    response_model=FindingOut,
    status_code=status.HTTP_201_CREATED,
)
def attach_spectrum(
    finding_id: UUID,
    body: AttachSpectrum,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    """Attach a spectrum the caller can read.

    Note this permits attaching someone else's PUBLISHED spectrum — that's
    the point of a commons, and how a Finding can compare your data against
    a published reference. It does not permit attaching their draft.
    """
    finding = _get_finding_for_owner(finding_id, user, db)

    spectrum = db.get(Spectrum, body.spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spectrum not found")
    require_owner_or_public(spectrum, user)

    existing = db.execute(
        select(FindingSpectrum).where(
            FindingSpectrum.finding_id == finding.id,
            FindingSpectrum.spectrum_id == spectrum.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That spectrum is already part of this finding.",
        )

    count = db.execute(
        select(func.count(FindingSpectrum.id)).where(FindingSpectrum.finding_id == finding.id)
    ).scalar_one()
    if count >= MAX_SPECTRA_PER_FINDING:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"A finding can hold at most {MAX_SPECTRA_PER_FINDING} spectra.",
        )

    db.add(
        FindingSpectrum(
            finding_id=finding.id,
            spectrum_id=spectrum.id,
            position=int(count),
            label=body.label,
        )
    )
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.delete("/findings/{finding_id}/spectra/{spectrum_id}", response_model=FindingOut)
def detach_spectrum(
    finding_id: UUID,
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    finding = _get_finding_for_owner(finding_id, user, db)
    link = db.execute(
        select(FindingSpectrum).where(
            FindingSpectrum.finding_id == finding.id,
            FindingSpectrum.spectrum_id == spectrum_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not part of this finding"
        )
    db.delete(link)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


# --- entries -------------------------------------------------------------


@router.post(
    "/findings/{finding_id}/entries",
    response_model=FindingOut,
    status_code=status.HTTP_201_CREATED,
)
def append_entry(
    finding_id: UUID,
    body: EntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    """Append a post to the thread. This is the 'add results step by step'
    action — new work arrives as a new entry rather than an edit."""
    finding = _get_finding_for_owner(finding_id, user, db)

    next_position = db.execute(
        select(func.coalesce(func.max(FindingEntry.position), -1) + 1).where(
            FindingEntry.finding_id == finding.id
        )
    ).scalar_one()

    db.add(
        FindingEntry(
            finding_id=finding.id,
            author_id=user.id,
            position=int(next_position),
            kind=body.kind,
            body_md=body.body_md,
            config=body.config,
        )
    )
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.patch("/findings/{finding_id}/entries/{entry_id}", response_model=FindingOut)
def update_entry(
    finding_id: UUID,
    entry_id: UUID,
    body: EntryUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    finding = _get_finding_for_owner(finding_id, user, db)
    entry = db.get(FindingEntry, entry_id)
    if entry is None or entry.finding_id != finding.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if body.body_md is not None:
        entry.body_md = body.body_md
    if body.config is not None:
        entry.config = body.config
    db.add(entry)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.delete("/findings/{finding_id}/entries/{entry_id}", response_model=FindingOut)
def delete_entry(
    finding_id: UUID,
    entry_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    finding = _get_finding_for_owner(finding_id, user, db)
    entry = db.get(FindingEntry, entry_id)
    if entry is None or entry.finding_id != finding.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    db.delete(entry)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.post("/findings/{finding_id}/entries/reorder", response_model=FindingOut)
def reorder_entries(
    finding_id: UUID,
    body: EntryReorder,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    """Reorder by supplying the complete entry list in the desired order.

    Requiring the FULL set, rather than accepting a partial reordering,
    means the resulting positions are always dense and unambiguous — a
    partial update would silently leave gaps or duplicate positions.
    """
    finding = _get_finding_for_owner(finding_id, user, db)
    entries = (
        db.execute(select(FindingEntry).where(FindingEntry.finding_id == finding.id))
        .scalars()
        .all()
    )

    by_id = {entry.id: entry for entry in entries}
    if set(body.entry_ids) != set(by_id) or len(body.entry_ids) != len(by_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Supply every entry id exactly once, in the order you want.",
        )

    for position, entry_id in enumerate(body.entry_ids):
        by_id[entry_id].position = position
        db.add(by_id[entry_id])
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


# --- images ------------------------------------------------------------
#
# Author-supplied raster images (figures, graphical abstract). Unlike
# analysis entries — which store parameters and recompute their figure from
# live spectrum data — these can't be regenerated, so they're the user's own
# data: stored in the same object store as their spectra, keyed under the
# owner, and streamed back through `/file` under the finding's read gate.


@router.post(
    "/findings/{finding_id}/images",
    response_model=FindingImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_finding_image(
    finding_id: UUID,
    file: UploadFile,
    kind: str = Form("figure"),
    caption: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingImageOut:
    """Attach an image to a finding. Owner-only. Idempotent on identical
    bytes: re-uploading the same file returns the existing row."""
    finding = _get_finding_for_owner(finding_id, user, db)

    if kind not in FINDING_IMAGE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kind must be one of {sorted(FINDING_IMAGE_KINDS)}",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Empty file")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image must be at most {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )

    # Trust the bytes, not the client's declared Content-Type.
    content_type = _sniff_image_type(raw)
    ext = IMAGE_CONTENT_TYPE_EXT.get(content_type or "")
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Image must be PNG, JPEG, or WebP.",
        )

    content_hash = hashlib.sha256(raw).hexdigest()
    existing = db.execute(
        select(FindingImage).where(
            FindingImage.finding_id == finding.id,
            FindingImage.content_hash == content_hash,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _serialize_image(existing)

    count = db.execute(
        select(func.count(FindingImage.id)).where(FindingImage.finding_id == finding.id)
    ).scalar_one()
    if count >= MAX_IMAGES_PER_FINDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A finding can hold at most {MAX_IMAGES_PER_FINDING} images.",
        )

    key = f"figures/{finding.owner_id}/{finding.id}/{uuid4().hex}.{ext}"
    upload_bytes(
        bucket=settings.S3_BUCKET_FIGURES,
        key=key,
        data=raw,
        content_type=content_type,
    )

    next_position = db.execute(
        select(func.coalesce(func.max(FindingImage.position), -1) + 1).where(
            FindingImage.finding_id == finding.id
        )
    ).scalar_one()

    image = FindingImage(
        finding_id=finding.id,
        uploaded_by=user.id,
        kind=kind,
        caption=caption or None,
        position=int(next_position),
        storage_bucket=settings.S3_BUCKET_FIGURES,
        storage_key=key,
        content_type=content_type,
        content_hash=content_hash,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return _serialize_image(image)


@router.patch("/findings/{finding_id}/images/{image_id}", response_model=FindingImageOut)
def update_finding_image(
    finding_id: UUID,
    image_id: UUID,
    body: ImageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingImageOut:
    """Owner-only. Edit the caption and/or move the image to a new position
    (positions are renormalized dense afterwards)."""
    finding = _get_finding_for_owner(finding_id, user, db)
    image = db.get(FindingImage, image_id)
    if image is None or image.finding_id != finding.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    if body.caption is not None:
        image.caption = body.caption or None

    if body.position is not None:
        ordered = [img for img in _images(finding.id, db) if img.id != image.id]
        target = max(0, min(body.position, len(ordered)))
        ordered.insert(target, image)
        for position, img in enumerate(ordered):
            img.position = position
            db.add(img)

    db.add(image)
    db.commit()
    db.refresh(image)
    return _serialize_image(image)


@router.delete(
    "/findings/{finding_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_finding_image(
    finding_id: UUID,
    image_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Owner-only. Drops the row and renormalizes positions. The stored
    object is deliberately left in place — same as raw files, whose bytes
    are never deleted at the app layer."""
    finding = _get_finding_for_owner(finding_id, user, db)
    image = db.get(FindingImage, image_id)
    if image is None or image.finding_id != finding.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    db.delete(image)
    db.flush()
    _renormalize_image_positions(finding.id, db)
    db.commit()


@router.post("/findings/{finding_id}/images/reorder", response_model=FindingOut)
def reorder_finding_images(
    finding_id: UUID,
    body: ImageReorder,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FindingOut:
    """Owner-only. Supply the complete image-id list in the desired order —
    the full set exactly once, same rule as entry reordering."""
    finding = _get_finding_for_owner(finding_id, user, db)
    images = (
        db.execute(select(FindingImage).where(FindingImage.finding_id == finding.id))
        .scalars()
        .all()
    )

    by_id = {image.id: image for image in images}
    if set(body.image_ids) != set(by_id) or len(body.image_ids) != len(by_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Supply every image id exactly once, in the order you want.",
        )

    for position, image_id in enumerate(body.image_ids):
        by_id[image_id].position = position
        db.add(by_id[image_id])
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.get("/findings/{finding_id}/images/{image_id}/file")
def get_finding_image_file(
    finding_id: UUID,
    image_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> Response:
    """Stream the image bytes, gated by the finding's read rule (a draft is
    owner-only). Content-addressed key -> long immutable cache."""
    finding = db.get(Finding, finding_id)
    require_finding_readable(finding, user)  # 404 on missing or non-readable

    image = db.get(FindingImage, image_id)
    if image is None or image.finding_id != finding_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not object_exists(image.storage_bucket, image.storage_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image object missing")

    data = download_bytes(image.storage_bucket, image.storage_key)
    return Response(
        content=data,
        media_type=image.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
