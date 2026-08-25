"""Module 4b: the Trending feed.

## Ranking policy — the quarantine rule this file used to assert is GONE

This docstring previously said Trending was the ONE place vote counts may
influence ordering, per the architecture doc's Module 4 quarantine rule.
That rule has been deliberately reversed by a product decision: engagement
now also feeds the default `relevance` ordering in `app.routers.search` and
in `/feed`, via the shared scorer in `app.ranking`. See that module for the
tradeoff and the mitigations.

Trending nonetheless stays a SEPARATE endpoint, because it answers a
different question — "what is hot right now" rather than "what best matches
my query" — and the difference is not cosmetic:

* Trending counts votes inside a fixed window and INNER-joins them, so a
  spectrum with zero votes is correctly absent. "Trending with no votes" is
  not a thing.
* Search must NOT copy that join. Its job is to return everything matching
  the filters, so it uses a correlated scalar vote count that yields 0
  rather than dropping the row. An inner join there would silently hide the
  large majority of the corpus — every spectrum nobody has voted on yet.

Do not merge the two on the grounds that they now share a signal.

Mounted with no prefix — the route is `/trending`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.enums import SpectrumState
from app.models.social import Vote
from app.models.spectrum import Spectrum

router = APIRouter(tags=["trending"])


class TrendingItem(BaseModel):
    id: UUID
    title: str | None
    owner_id: UUID
    published_at: datetime | None
    vote_count: int

    model_config = {"from_attributes": True}


@router.get("/trending", response_model=list[TrendingItem])
def get_trending(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    window_days: int = Query(default=7, ge=1, le=365),
    db: Session = Depends(get_db),
) -> list[TrendingItem]:
    """Published spectra only, ranked by count of votes cast within the
    trailing `window_days` window (descending), ties broken by
    `published_at` descending.

    Design choice: only spectra with at least 1 vote in the window are
    included (inner join, not left join) — an all-zero Trending page would
    look broken/uninformative on a fresh install or for spectra nobody has
    engaged with yet, so those are simply omitted rather than padding the
    list with zero-vote rows in arbitrary order.
    """
    window_start = datetime.now(UTC) - timedelta(days=window_days)

    vote_count_col = func.count(Vote.id).label("vote_count")
    rows = db.execute(
        select(Spectrum.id, Spectrum.title, Spectrum.owner_id, Spectrum.published_at, vote_count_col)
        .join(Vote, Vote.spectrum_id == Spectrum.id)
        .where(Spectrum.state == SpectrumState.published)
        .where(Vote.created_at >= window_start)
        .group_by(Spectrum.id)
        .order_by(vote_count_col.desc(), Spectrum.published_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return [
        TrendingItem(
            id=row.id,
            title=row.title,
            owner_id=row.owner_id,
            published_at=row.published_at,
            vote_count=row.vote_count,
        )
        for row in rows
    ]
