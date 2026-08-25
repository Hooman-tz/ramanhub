"""Aggregate public contribution numbers for one user's profile.

## Why this is a module and not inline in the router

`GET /users/by-handle/{handle}` used to run two scalar counts. This computes
nine, and putting nine subqueries inline in a route handler is how a profile
page quietly becomes the slowest endpoint in the app. Keeping them here means
one place to add caching or denormalized counters when that day comes.

## What is counted, and what deliberately is not

Everything here is either an act of **production** by this user, or **reuse
by other people**. Both are things you can point at.

Two rules the queries below encode:

* **Published only.** Draft work never appears in a public count. Including
  it would leak how much unpublished work someone is sitting on, which is the
  reason `routers.users` already scoped its two original counts this way.
* **Self-reuse doesn't count.** "Used in N Findings" filters out Findings the
  spectrum's own owner wrote. A number you can raise by writing about your own
  data is a number about writing, not about reuse.

Fork counts are absent on purpose: `spectra` has no `forked_from` column, so
lineage is not recorded and any "forks" figure would be invented. That needs
a schema change before it can be reported honestly.
"""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from app.models.enums import FindingState, SpectrumState
from app.models.finding import Finding, FindingSpectrum
from app.models.graph import Follow
from app.models.social import Comment, Share, Vote
from app.models.spectrum import Spectrum


class ProfileStats(BaseModel):
    """Public, brag-worthy numbers. Every one of them should be clickable
    through to the thing it counts — a count with no destination is a number
    the reader has to take on faith."""

    followers: int = 0
    following: int = 0
    spectra_published: int = 0
    findings_published: int = 0
    doi_linked: int = 0
    votes_received: int = 0
    shares_received: int = 0
    comments_written: int = 0
    # Reuse: other people's Findings that include this user's spectra.
    reuse_findings: int = 0
    reuse_groups: int = 0


def _count(db: Session, stmt) -> int:
    return db.scalar(stmt) or 0


def compute_profile_stats(user_id: UUID, db: Session) -> ProfileStats:
    published_spectra = select(Spectrum.id).where(
        Spectrum.owner_id == user_id, Spectrum.state == SpectrumState.published
    )
    published_findings = select(Finding.id).where(
        Finding.owner_id == user_id, Finding.state == FindingState.published
    )

    followers = _count(
        db, select(func.count()).select_from(Follow).where(Follow.followee_id == user_id)
    )
    following = _count(
        db, select(func.count()).select_from(Follow).where(Follow.follower_id == user_id)
    )

    spectra_published = _count(
        db,
        select(func.count())
        .select_from(Spectrum)
        .where(Spectrum.owner_id == user_id, Spectrum.state == SpectrumState.published),
    )
    findings_published = _count(
        db,
        select(func.count())
        .select_from(Finding)
        .where(Finding.owner_id == user_id, Finding.state == FindingState.published),
    )

    # DOI-linked work across both object types. This is the one count that is
    # externally verifiable — a DOI resolves or it doesn't — which is why it
    # is worth showing next to the softer engagement numbers.
    doi_linked = _count(
        db,
        select(func.count())
        .select_from(Spectrum)
        .where(
            Spectrum.owner_id == user_id,
            Spectrum.state == SpectrumState.published,
            Spectrum.doi.isnot(None),
        ),
    ) + _count(
        db,
        select(func.count())
        .select_from(Finding)
        .where(
            Finding.owner_id == user_id,
            Finding.state == FindingState.published,
            Finding.doi.isnot(None),
        ),
    )

    # Engagement RECEIVED, across both object types in one pass. The
    # dual-target CHECK on votes/shares guarantees exactly one of the two
    # columns is set per row, so an OR across the two subqueries cannot
    # double-count a single row.
    votes_received = _count(
        db,
        select(func.count())
        .select_from(Vote)
        .where(
            or_(
                Vote.spectrum_id.in_(published_spectra),
                Vote.finding_id.in_(published_findings),
            )
        ),
    )
    shares_received = _count(
        db,
        select(func.count())
        .select_from(Share)
        .where(
            or_(
                Share.spectrum_id.in_(published_spectra),
                Share.finding_id.in_(published_findings),
            )
        ),
    )

    comments_written = _count(
        db, select(func.count()).select_from(Comment).where(Comment.user_id == user_id)
    )

    # Reuse. A join from this user's published spectra to the Findings that
    # include them, excluding Findings this user owns — see the module
    # docstring on why self-reuse is not reuse.
    reuse_base = (
        select(Finding.id.label("finding_id"), Finding.owner_id.label("owner_id"))
        .join(FindingSpectrum, FindingSpectrum.finding_id == Finding.id)
        .join(Spectrum, Spectrum.id == FindingSpectrum.spectrum_id)
        .where(
            Spectrum.owner_id == user_id,
            Spectrum.state == SpectrumState.published,
            Finding.state == FindingState.published,
            Finding.owner_id != user_id,
        )
        .subquery()
    )
    reuse_findings = _count(
        db, select(func.count(distinct(reuse_base.c.finding_id))).select_from(reuse_base)
    )
    reuse_groups = _count(
        db, select(func.count(distinct(reuse_base.c.owner_id))).select_from(reuse_base)
    )

    return ProfileStats(
        followers=followers,
        following=following,
        spectra_published=spectra_published,
        findings_published=findings_published,
        doi_linked=doi_linked,
        votes_received=votes_received,
        shares_received=shares_received,
        comments_written=comments_written,
        reuse_findings=reuse_findings,
        reuse_groups=reuse_groups,
    )
