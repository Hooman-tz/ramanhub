"""The social feed: published Findings and spectra, one scrollable surface.

Mounted with no prefix — `GET /feed`.

Distinct from the two neighbouring surfaces, and the distinction is worth
keeping straight:

- `/search/spectra` — you know what you're looking for. Filters first,
  ranking second.
- `/trending` — pure engagement inside a short window. Deliberately
  inner-joined, so zero-vote items are excluded; a Trending page padded with
  untouched items reads as broken.
- `/feed` (here) — you don't know what you're looking for. Everything
  published, newest-and-liveliest first, including items with no votes yet.
  This is the "social media of scientists" surface.

Findings and spectra are scored with the SAME function (`app.ranking`), so
the two kinds interleave on comparable terms rather than one systematically
outranking the other because of how its score happened to be computed.

Pagination is offset-based, matching the rest of the API. A cursor would be
strictly better for an infinite scroll over a shifting ranking — offset
paging can repeat or skip an item when scores change mid-scroll — but the
tiebreak on a unique key keeps that rare, and cursors are a real complexity
cost to add before there's evidence of the problem (Scaling Posture).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import FindingState, SpectrumState
from app.models.finding import Finding, FindingSpectrum
from app.models.social import Comment, Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.ranking import relevance_score, vote_count_subquery

router = APIRouter(tags=["feed"])


class FeedAuthor(BaseModel):
    id: UUID
    handle: str | None
    display_name: str | None
    avatar_url: str | None
    orcid_id: str | None


class FeedItem(BaseModel):
    kind: Literal["finding", "spectrum"]
    id: UUID
    accession: str | None
    title: str | None
    summary: str | None
    author: FeedAuthor | None
    published_at: datetime | None
    vote_count: int
    comment_count: int
    doi: str | None
    tags: list | None = None
    # Findings only: how many spectra the thread covers, so a card can say
    # "4 spectra" without a second request per item.
    spectrum_count: int | None = None
    # Spectra only.
    material_type: str | None = None
    snr: float | None = None
    score: float = 0.0


def _author(user: User | None) -> FeedAuthor | None:
    if user is None:
        return None
    return FeedAuthor(
        id=user.id,
        handle=user.handle,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        orcid_id=user.orcid_id,
    )


def _truncate(text: str | None, limit: int = 280) -> str | None:
    """Card-sized summary. Cuts on a word boundary so the preview doesn't
    end mid-word."""
    if not text:
        return None
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rsplit(" ", 1)[0] + "..."


@router.get("/feed", response_model=list[FeedItem])
def get_feed(
    kind: Literal["all", "findings", "spectra"] = "all",
    trust_tier: Literal["doi_verified", "community"] | None = None,
    tag: str | None = None,
    author: str | None = Query(None, description="Filter to one contributor's handle."),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[FeedItem]:
    """The discovery feed.

    Both kinds are ranked in SQL, then merged and re-sorted in Python. That
    merge is honest about its limitation: with `kind=all`, `limit` is
    applied to each kind before merging, so a page can contain up to
    `limit` of each rather than exactly `limit` overall. Getting a true
    global top-N would need a UNION over two differently-shaped tables; at
    this corpus size the merge is indistinguishable in practice and far
    easier to read. Revisit when the feed is deep enough that it matters.
    """
    items: list[FeedItem] = []

    if kind in ("all", "findings"):
        votes = vote_count_subquery(Vote, Vote.finding_id, Finding.id)
        comments = (
            select(func.count(Comment.id))
            .where(Comment.finding_id == Finding.id)
            .scalar_subquery()
        )
        spectrum_count = (
            select(func.count(FindingSpectrum.id))
            .where(FindingSpectrum.finding_id == Finding.id)
            .scalar_subquery()
        )
        score = relevance_score(
            votes, func.coalesce(Finding.published_at, Finding.created_at), Finding.doi
        )

        query = (
            select(Finding, votes, comments, spectrum_count, score, User)
            .join(User, User.id == Finding.owner_id, isouter=True)
            .where(Finding.state == FindingState.published)
        )
        if trust_tier == "doi_verified":
            query = query.where(Finding.doi.is_not(None))
        elif trust_tier == "community":
            query = query.where(Finding.doi.is_(None))
        if tag:
            # Containment against a JSONB array; the tag is passed as a bound
            # parameter, never interpolated into the SQL text.
            query = query.where(Finding.tags.contains([tag.strip().lower()]))
        if author:
            query = query.where(User.handle == author.strip().lower())

        rows = db.execute(
            query.order_by(score.desc(), Finding.published_at.desc(), Finding.id)
            .limit(limit)
            .offset(offset)
        ).all()

        for finding, vote_count, comment_count, n_spectra, item_score, owner in rows:
            items.append(
                FeedItem(
                    kind="finding",
                    id=finding.id,
                    accession=finding.accession,
                    title=finding.title,
                    summary=_truncate(finding.abstract_md),
                    author=_author(owner),
                    published_at=finding.published_at,
                    vote_count=int(vote_count or 0),
                    comment_count=int(comment_count or 0),
                    doi=finding.doi,
                    tags=finding.tags,
                    spectrum_count=int(n_spectra or 0),
                    score=float(item_score or 0.0),
                )
            )

    if kind in ("all", "spectra"):
        votes = vote_count_subquery(Vote, Vote.spectrum_id, Spectrum.id)
        comments = (
            select(func.count(Comment.id))
            .where(Comment.spectrum_id == Spectrum.id)
            .scalar_subquery()
        )
        score = relevance_score(
            votes, func.coalesce(Spectrum.published_at, Spectrum.created_at), Spectrum.doi
        )

        query = (
            select(Spectrum, votes, comments, score, User)
            .join(User, User.id == Spectrum.owner_id, isouter=True)
            .where(Spectrum.state == SpectrumState.published)
        )
        if trust_tier == "doi_verified":
            query = query.where(Spectrum.doi.is_not(None))
        elif trust_tier == "community":
            query = query.where(Spectrum.doi.is_(None))
        if author:
            query = query.where(User.handle == author.strip().lower())
        if tag:
            # Spectra have no tags; a tag filter simply excludes them rather
            # than silently returning unfiltered spectra alongside filtered
            # findings.
            query = query.where(False)

        rows = db.execute(
            query.order_by(score.desc(), Spectrum.published_at.desc(), Spectrum.id)
            .limit(limit)
            .offset(offset)
        ).all()

        for spectrum, vote_count, comment_count, item_score, owner in rows:
            items.append(
                FeedItem(
                    kind="spectrum",
                    id=spectrum.id,
                    accession=spectrum.accession,
                    title=spectrum.title,
                    summary=_truncate(spectrum.description),
                    author=_author(owner),
                    published_at=spectrum.published_at,
                    vote_count=int(vote_count or 0),
                    comment_count=int(comment_count or 0),
                    doi=spectrum.doi,
                    material_type=spectrum.material_type,
                    snr=float(spectrum.snr) if spectrum.snr is not None else None,
                    score=float(item_score or 0.0),
                )
            )

    # An aware sentinel: published_at is timezone-aware, and comparing it
    # against a naive datetime.min raises rather than sorting.
    oldest = datetime.min.replace(tzinfo=UTC)
    items.sort(key=lambda item: (item.score, item.published_at or oldest), reverse=True)
    return items[:limit]
