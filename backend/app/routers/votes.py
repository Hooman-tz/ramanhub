"""Module 4b: upvotes on spectra and on Findings. Mounted with no prefix —
`/spectra/{spectrum_id}/votes` and `/findings/{finding_id}/votes`.

The two targets share the `votes` table (see `app.models.social` for why),
and each route filters on its OWN target column. That is only correct
because the table's CHECK constraint guarantees exactly one target is set,
so a finding-vote always has a NULL `spectrum_id` and can never be counted
in a spectrum's tally.

Deliberately quarantined from core search/discovery: vote counts here never
feed `app.routers.search`'s ranking, only the separate Trending feed
(`app.routers.trending`) and the social `/v1/feed` blend.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import idempotency
from app.auth.deps import get_current_full_user, get_current_user_optional
from app.db.session import get_db
from app.models.finding import Finding
from app.models.social import Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_finding_readable, require_owner_or_public
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
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_votes),
):
    # A replayed POST (proxy retry / HTTP/2 reset carrying the same client
    # `Idempotency-Key`) must not flip the toggle a second time — return the
    # first run's answer. No header -> None, behaviour unchanged.
    hit = idempotency.check(db, user.id, request)
    if hit is not None:
        return JSONResponse(hit["body"], status_code=hit["status"])

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
        off = VoteToggleResponse(voted=False, count=_vote_count(spectrum.id, db))
        idempotency.record(db, user.id, request, status.HTTP_200_OK, off)
        return off

    db.commit()
    on = VoteToggleResponse(voted=True, count=_vote_count(spectrum.id, db))
    idempotency.record(db, user.id, request, status.HTTP_200_OK, on)
    return on


def _finding_vote_count(finding_id: UUID, db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(Vote).where(Vote.finding_id == finding_id)
    ) or 0


def _get_visible_finding_or_404(finding_id: UUID, user: User | None, db: Session) -> Finding:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_finding_readable(finding, user)
    return finding


@router.post("/findings/{finding_id}/votes", response_model=VoteToggleResponse)
def toggle_finding_vote(
    finding_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_votes),
):
    """Same insert-first, treat-conflict-as-toggle-off pattern as the
    spectrum route above — see its comments for why that ordering is
    race-safe."""
    hit = idempotency.check(db, user.id, request)
    if hit is not None:
        return JSONResponse(hit["body"], status_code=hit["status"])

    finding = _get_visible_finding_or_404(finding_id, user, db)

    try:
        with db.begin_nested():
            db.add(Vote(finding_id=finding.id, user_id=user.id))
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Vote).where(Vote.finding_id == finding.id, Vote.user_id == user.id)
        )
        if existing is not None:
            db.delete(existing)
            db.commit()
        off = VoteToggleResponse(voted=False, count=_finding_vote_count(finding.id, db))
        idempotency.record(db, user.id, request, status.HTTP_200_OK, off)
        return off

    db.commit()
    on = VoteToggleResponse(voted=True, count=_finding_vote_count(finding.id, db))
    idempotency.record(db, user.id, request, status.HTTP_200_OK, on)
    return on


@router.get("/findings/{finding_id}/votes", response_model=VoteStatusResponse)
def get_finding_votes(
    finding_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> VoteStatusResponse:
    finding = _get_visible_finding_or_404(finding_id, user, db)
    voted_by_me = False
    if user is not None:
        voted_by_me = (
            db.scalar(
                select(Vote).where(Vote.finding_id == finding.id, Vote.user_id == user.id)
            )
            is not None
        )
    return VoteStatusResponse(
        count=_finding_vote_count(finding.id, db), voted_by_me=voted_by_me
    )


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
