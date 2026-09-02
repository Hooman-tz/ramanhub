"""Shares — re-broadcasting a spectrum or Finding. Mounted with no prefix:
`/spectra/{id}/shares`, `/findings/{id}/shares`.

Structurally a sibling of `routers.votes`: same dual-target table, same
insert-first-then-treat-conflict-as-toggle-off ordering (see that module for
why that is the race-safe direction), same full-account requirement.

What differs is intent. A vote says "this is good"; a share says "my
followers should see this", so a share carries an optional `comment` — the
quote-post shape — and is what `/feed?filter=following` surfaces from people
you follow beyond their own publications.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import idempotency
from app.auth.deps import get_current_full_user, get_current_user_optional
from app.db.session import get_db
from app.models.finding import Finding
from app.models.social import Share
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_finding_readable, require_owner_or_public
from app.ratelimit import rate_limit_shares

router = APIRouter(tags=["shares"])

MAX_SHARE_COMMENT = 500


class ShareRequest(BaseModel):
    comment: str | None = Field(None, max_length=MAX_SHARE_COMMENT)


class ShareToggleResponse(BaseModel):
    shared: bool
    count: int


class ShareStatusResponse(BaseModel):
    count: int
    shared_by_me: bool


def _spectrum_share_count(spectrum_id: UUID, db: Session) -> int:
    return (
        db.scalar(select(func.count()).select_from(Share).where(Share.spectrum_id == spectrum_id))
        or 0
    )


def _finding_share_count(finding_id: UUID, db: Session) -> int:
    return (
        db.scalar(select(func.count()).select_from(Share).where(Share.finding_id == finding_id))
        or 0
    )


@router.post("/spectra/{spectrum_id}/shares", response_model=ShareToggleResponse)
def toggle_spectrum_share(
    spectrum_id: UUID,
    request: Request,
    body: ShareRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_shares),
):
    # A replayed POST carrying the same client `Idempotency-Key` must not
    # flip the toggle again — replay the first run's answer. No header -> None.
    hit = idempotency.check(db, user.id, request)
    if hit is not None:
        return JSONResponse(hit["body"], status_code=hit["status"])

    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # Sharing something you can see but the public cannot would push a draft
    # into other people's feeds, so readability is checked the same way every
    # other spectrum read is.
    require_owner_or_public(spectrum, user)

    try:
        with db.begin_nested():
            db.add(
                Share(
                    spectrum_id=spectrum.id,
                    user_id=user.id,
                    comment=body.comment if body else None,
                )
            )
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Share).where(Share.spectrum_id == spectrum.id, Share.user_id == user.id)
        )
        if existing is not None:
            db.delete(existing)
            db.commit()
        off = ShareToggleResponse(shared=False, count=_spectrum_share_count(spectrum.id, db))
        idempotency.record(db, user.id, request, status.HTTP_200_OK, off)
        return off

    db.commit()
    on = ShareToggleResponse(shared=True, count=_spectrum_share_count(spectrum.id, db))
    idempotency.record(db, user.id, request, status.HTTP_200_OK, on)
    return on


@router.post("/findings/{finding_id}/shares", response_model=ShareToggleResponse)
def toggle_finding_share(
    finding_id: UUID,
    request: Request,
    body: ShareRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_shares),
):
    hit = idempotency.check(db, user.id, request)
    if hit is not None:
        return JSONResponse(hit["body"], status_code=hit["status"])

    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_finding_readable(finding, user)

    try:
        with db.begin_nested():
            db.add(
                Share(
                    finding_id=finding.id,
                    user_id=user.id,
                    comment=body.comment if body else None,
                )
            )
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Share).where(Share.finding_id == finding.id, Share.user_id == user.id)
        )
        if existing is not None:
            db.delete(existing)
            db.commit()
        off = ShareToggleResponse(shared=False, count=_finding_share_count(finding.id, db))
        idempotency.record(db, user.id, request, status.HTTP_200_OK, off)
        return off

    db.commit()
    on = ShareToggleResponse(shared=True, count=_finding_share_count(finding.id, db))
    idempotency.record(db, user.id, request, status.HTTP_200_OK, on)
    return on


@router.get("/spectra/{spectrum_id}/shares", response_model=ShareStatusResponse)
def spectrum_share_status(
    spectrum_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> ShareStatusResponse:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)

    shared = False
    if user is not None:
        shared = (
            db.scalar(
                select(func.count())
                .select_from(Share)
                .where(Share.spectrum_id == spectrum.id, Share.user_id == user.id)
            )
            or 0
        ) > 0
    return ShareStatusResponse(count=_spectrum_share_count(spectrum.id, db), shared_by_me=shared)


@router.get("/findings/{finding_id}/shares", response_model=ShareStatusResponse)
def finding_share_status(
    finding_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> ShareStatusResponse:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_finding_readable(finding, user)

    shared = False
    if user is not None:
        shared = (
            db.scalar(
                select(func.count())
                .select_from(Share)
                .where(Share.finding_id == finding.id, Share.user_id == user.id)
            )
            or 0
        ) > 0
    return ShareStatusResponse(count=_finding_share_count(finding.id, db), shared_by_me=shared)
