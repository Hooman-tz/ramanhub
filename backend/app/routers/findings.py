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

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user, get_current_user_optional
from app.db.session import get_db
from app.doi_lookup import lookup_doi
from app.models.accession import next_finding_accession
from app.models.enums import FindingEntryKind, FindingState, SpectrumState
from app.models.finding import Finding, FindingEntry, FindingSpectrum
from app.models.social import Comment, Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_finding_readable, require_owner_or_public

router = APIRouter(prefix="/v1", tags=["findings"])

MAX_TAGS = 10
MAX_TAG_LENGTH = 40
MAX_SPECTRA_PER_FINDING = 200


# --------------------------------------------------------------- schemas


class FindingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    abstract_md: str | None = Field(default=None, max_length=20_000)
    tags: list[str] | None = None


class FindingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    abstract_md: str | None = Field(default=None, max_length=20_000)
    tags: list[str] | None = None
    doi: str | None = None


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
    publication_metadata: dict | None
    tags: list | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    entries: list[EntryOut] = []
    spectra: list[MemberSpectrumOut] = []
    vote_count: int = 0
    comment_count: int = 0


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
        publication_metadata=finding.publication_metadata,
        tags=finding.tags,
        published_at=finding.published_at,
        created_at=finding.created_at,
        updated_at=finding.updated_at,
    )

    if include_body:
        entries = db.execute(
            select(FindingEntry)
            .where(FindingEntry.finding_id == finding.id)
            .order_by(FindingEntry.position, FindingEntry.created_at)
        ).scalars().all()
        out.entries = [EntryOut.model_validate(e) for e in entries]

        out.spectra = [
            MemberSpectrumOut(
                spectrum_id=spectrum.id,
                accession=spectrum.accession,
                title=spectrum.title,
                label=link.label,
                position=link.position,
                state=spectrum.state.value
                if hasattr(spectrum.state, "value")
                else spectrum.state,
            )
            for link, spectrum in _members(finding.id, db)
        ]

    out.vote_count = int(
        db.execute(
            select(func.count(Vote.id)).where(Vote.finding_id == finding.id)
        ).scalar_one()
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
    db: Session = Depends(get_db),
    # Guests may draft a Finding, same try-before-login rule as uploading.
    # Publishing is what requires a real account.
    user: User = Depends(get_current_user),
) -> FindingOut:
    finding = Finding(
        accession=next_finding_accession(db),
        owner_id=user.id,
        title=body.title,
        abstract_md=body.abstract_md,
        tags=_normalize_tags(body.tags),
        state=FindingState.draft,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


@router.get("/findings", response_model=list[FindingOut])
def list_my_findings(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[FindingOut]:
    """The caller's own Findings, in any state — the personal workspace
    view. Public discovery goes through `/v1/feed` and `/search`."""
    findings = db.execute(
        select(Finding)
        .where(Finding.owner_id == user.id)
        .order_by(Finding.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
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
        finding.publication_metadata = (
            {**metadata.model_dump(), "resolved": True}
            if metadata is not None
            else {"doi": doi, "resolved": False}
        )

    db.add(finding)
    db.commit()
    db.refresh(finding)
    return serialize_finding(finding, db)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not part of this finding")
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
    entries = db.execute(
        select(FindingEntry).where(FindingEntry.finding_id == finding.id)
    ).scalars().all()

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
