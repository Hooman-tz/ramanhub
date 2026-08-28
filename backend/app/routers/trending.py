"""Module 4b: the Trending feed.

Per raman-platform-architecture-v2.md's MODULE 4 requirement — "Social
features (upvote/comment) stay quarantined to a separate Trending feed and
never affect core search ranking" — this is the ONE place in the codebase
where vote counts are allowed to influence ordering. `app.routers.search`
(owned by a different module/agent) ranks by `published_at` only and MUST
NOT be touched to incorporate vote counts; Trending and Search are
deliberately separate feeds with different semantics. Do not merge them.

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
        select(Spectrum.id, Spectrum.title, Spectrum.published_at, vote_count_col)
        .join(Vote, Vote.spectrum_id == Spectrum.id)
        .where(
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == "visible",
        )
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
            published_at=row.published_at,
            vote_count=row.vote_count,
        )
        for row in rows
    ]
