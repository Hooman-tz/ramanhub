"""Module 4a: the typeahead behind the global search palette.

One request, four groups — compounds, spectra, findings, people — so that a
single keystroke costs one round trip rather than four. The alternative
(a per-entity endpoint called in parallel) loses on every axis that matters
here: every browser call crosses the Next.js `/api` rewrite, so four calls
quadruple that hop; a rate limit only means something if one keystroke spends
one slot; the trigram threshold is a per-transaction setting, so four calls
would need four of them; and the group order and per-group caps are product
decisions the server should own rather than re-derive in each client.

Two constraints inherited from `search.py`, both load-bearing:

- **No social signal.** Nothing here joins `app.models.social` or orders by
  votes, comments or trending. Ranking is text only. `search.py`'s module
  docstring is the authority; `test_suggest_ranking_ignores_votes` is the guard.
- **The reference corpus is not part of the commons.** The spectra group runs
  through `exclude_reference_library`, or a search for "calcite" returns the
  same seeded RRUFF row twice — once as a compound, once as a spectrum — and
  buries the user uploads this group exists to surface.

A note on people. `co-author-field.tsx` was written on the principle that
nobody gets to enumerate the user table, and that still holds: this group is
strictly narrower than the `/users/suggested` list that already ships, which
publishes public profiles to anonymous callers ranked by follower count. Here
there is a minimum query length, a hard cap, no `offset` — so there is no way
to page through the directory — and every field returned is one already
rendered on the public profile the result links to.

Findings are a first: `/v1/findings` is the owner's own workspace list, so
until now public discovery of a finding went only through `/v1/feed`. Hence
the explicit `state == published` predicate rather than a shared helper.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.community import public_profile_predicates
from app.db.session import get_db
from app.models.enums import FindingState, SpectrumState
from app.models.finding import Finding
from app.models.reference import ReferenceCurationStatus, ReferenceEntry
from app.models.spectrum import Spectrum
from app.models.user import User
from app.ratelimit import rate_limit_search_suggest
from app.routers.search import exclude_reference_library
from app.textsearch import MIN_QUERY_LENGTH, apply_threshold, text_predicate, text_rank

router = APIRouter(prefix="/v1/search", tags=["search"])

SuggestKind = Literal["compound", "spectrum", "finding", "person"]

# Fixed, deliberately not sorted by score. A palette is a muscle-memory
# surface: groups that reorder between keystrokes are worse to use than a
# first row that is occasionally second-best.
GROUP_ORDER: list[tuple[SuggestKind, str]] = [
    ("compound", "Compounds"),
    ("spectrum", "Spectra"),
    ("finding", "Findings"),
    ("person", "People"),
]


class SuggestItem(BaseModel):
    kind: SuggestKind
    id: UUID
    title: str
    subtitle: str | None = None
    badge: str | None = None
    handle: str | None = None
    accession: str | None = None
    avatar_url: str | None = None
    score: float


class SuggestGroup(BaseModel):
    kind: SuggestKind
    label: str
    items: list[SuggestItem]
    # More matches exist beyond the cap. Free to compute: fetch limit + 1.
    truncated: bool


class SuggestResponse(BaseModel):
    query: str
    # An ordered array rather than a keyed object, so the server's group order
    # survives JSON round-tripping. No `href` anywhere: mobile will route
    # differently from web, so mapping a kind to a screen is a client concern.
    groups: list[SuggestGroup]


def _compounds(db: Session, q: str, limit: int) -> list[SuggestItem]:
    """One row per compound, not one per measurement.

    The imported corpus holds many spectra of the same mineral — 22 entries
    named "Andradite" in the current import. Listed plainly, a five-slot
    palette group answers "andradite" with the same word five times, which
    tells the user nothing. DISTINCT ON keeps the best-ranked entry per name;
    the browse list still shows every individual entry, because there each row
    is a spectrum you might actually want to open.
    """
    rank = text_rank(ReferenceEntry.compound_name, ReferenceEntry.search_text, q)
    name = func.lower(ReferenceEntry.compound_name)
    best_per_name = (
        select(ReferenceEntry.id.label("id"), rank.label("score"))
        .where(
            ReferenceEntry.curation_status != ReferenceCurationStatus.removed,
            text_predicate(ReferenceEntry.search_text, q),
        )
        # Postgres requires DISTINCT ON's expression to lead the ORDER BY;
        # the rest of the key decides which duplicate survives.
        .distinct(name)
        .order_by(name, rank.desc(), ReferenceEntry.trust_tier.asc())
        .subquery()
    )
    rows = db.execute(
        select(ReferenceEntry, best_per_name.c.score)
        .join(best_per_name, best_per_name.c.id == ReferenceEntry.id)
        .order_by(
            best_per_name.c.score.desc(),
            ReferenceEntry.trust_tier.asc(),
            ReferenceEntry.compound_name.asc(),
        )
        .limit(limit)
    ).all()
    return [
        SuggestItem(
            kind="compound",
            id=entry.id,
            title=entry.compound_name,
            subtitle=entry.chemical_formula or entry.mineral_name,
            badge=entry.trust_tier.value,
            score=float(score),
        )
        for entry, score in rows
    ]


def _spectra(db: Session, q: str, limit: int) -> list[SuggestItem]:
    rank = text_rank(Spectrum.title, Spectrum.search_text, q)
    rows = (
        exclude_reference_library(
            db.query(Spectrum, rank.label("score")).filter(
                Spectrum.state == SpectrumState.published,
                Spectrum.moderation_status == "visible",
                text_predicate(Spectrum.search_text, q),
            )
        )
        .order_by(rank.desc(), Spectrum.published_at.desc(), Spectrum.id)
        .limit(limit)
        .all()
    )
    return [
        SuggestItem(
            kind="spectrum",
            id=spectrum.id,
            title=spectrum.title or spectrum.accession or "Untitled spectrum",
            subtitle=spectrum.material_type,
            badge="DOI" if spectrum.doi else spectrum.modality.value,
            accession=spectrum.accession,
            score=float(score),
        )
        for spectrum, score in rows
    ]


def _findings(db: Session, q: str, limit: int) -> list[SuggestItem]:
    rank = text_rank(Finding.title, Finding.search_text, q)
    rows = (
        db.query(Finding, rank.label("score"))
        .filter(
            Finding.state == FindingState.published,
            text_predicate(Finding.search_text, q),
        )
        .order_by(rank.desc(), Finding.published_at.desc(), Finding.id)
        .limit(limit)
        .all()
    )
    return [
        SuggestItem(
            kind="finding",
            id=finding.id,
            title=finding.title,
            subtitle=", ".join(finding.tags[:3]) if finding.tags else None,
            accession=finding.accession,
            score=float(score),
        )
        for finding, score in rows
    ]


def _people(db: Session, q: str, limit: int) -> list[SuggestItem]:
    rank = text_rank(User.profile_handle, User.search_text, q)
    rows = (
        db.query(User, rank.label("score"))
        .filter(*public_profile_predicates(), text_predicate(User.search_text, q))
        .order_by(rank.desc(), User.created_at.desc(), User.id)
        .limit(limit)
        .all()
    )
    return [
        SuggestItem(
            kind="person",
            id=user.id,
            title=user.display_name or user.profile_handle,
            subtitle=user.affiliation,
            handle=user.profile_handle,
            avatar_url=user.avatar_url,
            score=float(score),
        )
        for user, score in rows
    ]


_FINDERS = {
    "compound": _compounds,
    "spectrum": _spectra,
    "finding": _findings,
    "person": _people,
}


@router.get(
    "/suggest",
    response_model=SuggestResponse,
    dependencies=[Depends(rate_limit_search_suggest)],
)
def suggest(
    q: str = Query(..., description="What the user has typed so far."),
    limit: int = Query(5, ge=1, le=10, description="Cap per group, not overall."),
    db: Session = Depends(get_db),
) -> SuggestResponse:
    """Grouped typeahead across compounds, spectra, findings and people.

    Public and unauthenticated: everything reachable here is already readable
    without an account. Drafts and embargoed spectra never appear, and neither
    does a profile whose owner did not publish one.

    A query shorter than two characters returns empty groups with a 200 rather
    than a 422. The client passes through that state on the first keystroke of
    every search, and making it an error would mean every caller has to
    special-case the most common request it will ever send.

    Deliberately has no `offset`. Paging a typeahead is meaningless, and its
    absence is what keeps the people group from becoming a walkable directory.
    """
    query = q.strip()
    if len(query) < MIN_QUERY_LENGTH:
        return SuggestResponse(
            query=query,
            groups=[
                SuggestGroup(kind=kind, label=label, items=[], truncated=False)
                for kind, label in GROUP_ORDER
            ],
        )

    apply_threshold(db)
    groups = []
    for kind, label in GROUP_ORDER:
        # One extra row is all it takes to know whether there are more.
        found = _FINDERS[kind](db, query, limit + 1)
        groups.append(
            SuggestGroup(
                kind=kind,
                label=label,
                items=found[:limit],
                truncated=len(found) > limit,
            )
        )
    return SuggestResponse(query=query, groups=groups)
