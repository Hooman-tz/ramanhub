"""Module 4b: upvotes on spectra. Mounted with no prefix — full routes are
`/spectra/{spectrum_id}/votes`.

Deliberately quarantined from core search/discovery: vote counts here never
feed `app.routers.search`'s ranking, only the separate Trending feed
(`app.routers.trending`).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user_optional
from app.db.session import get_db
from app.models.social import Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_owner_or_public
from app.ratelimit import rate_limit_votes

router = APIRouter(tags=["votes"])


class VoteToggleResponse(BaseModel):
    voted: bool
    count: int


class VoteStatusResponse(BaseModel):
    count: int
    voted_by_me: bool


def _get_visible_spectrum_or_404(spectrum_id: UUID, user: User | None, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)
    return spectrum


def _vote_count(spectrum_id: UUID, db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Vote).where(Vote.spectrum_id == spectrum_id)) or 0


@router.post("/spectra/{spectrum_id}/votes", response_model=VoteToggleResponse)
def toggle_vote(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_votes),
) -> VoteToggleResponse:
    spectrum = _get_visible_spectrum_or_404(spectrum_id, user, db)

    try:
        # Insert inside a SAVEPOINT (begin_nested) rather than committing
        # the whole session directly: if the unique (spectrum_id, user_id)
        # constraint is hit, only this nested SAVEPOINT is rolled back on
        # the way out of the `with` block, leaving the rest of the
        # session's already-flushed/committed state (e.g. the spectrum
        # itself) untouched.
        with db.begin_nested():
            db.add(Vote(spectrum_id=spectrum.id, user_id=user.id))
            db.flush()
    except IntegrityError:
        # Already voted -> race-safe toggle-off: attempt the insert first,
        # and treat the constraint violation as "now remove the existing
        # vote" rather than pre-checking-then-inserting.
        existing = db.scalar(
            select(Vote).where(Vote.spectrum_id == spectrum.id, Vote.user_id == user.id)
        )
        if existing is not None:
            db.delete(existing)
            db.commit()
        return VoteToggleResponse(voted=False, count=_vote_count(spectrum.id, db))

    db.commit()
    return VoteToggleResponse(voted=True, count=_vote_count(spectrum.id, db))


@router.get("/spectra/{spectrum_id}/votes", response_model=VoteStatusResponse)
def get_votes(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> VoteStatusResponse:
    spectrum = _get_visible_spectrum_or_404(spectrum_id, user, db)
    count = _vote_count(spectrum.id, db)
    voted_by_me = False
    if user is not None:
        existing = db.scalar(
            select(Vote).where(Vote.spectrum_id == spectrum.id, Vote.user_id == user.id)
        )
        voted_by_me = existing is not None
    return VoteStatusResponse(count=count, voted_by_me=voted_by_me)
