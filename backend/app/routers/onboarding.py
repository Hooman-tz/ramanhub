"""First-run onboarding: handle availability, people suggestions, and the
one-shot "finish setting up my profile" write. Mounted at prefix `/v1`.

Distinct from `PATCH /users/me` (general profile edits): this endpoint is the
gate that flips `onboarded_at`, and it records a `HandleHistory` row when it
changes a handle the user already had so old `/u/<handle>` links keep
resolving.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user_optional
from app.db.session import get_db
from app.handles import InvalidHandleError, normalize_handle, validate_handle
from app.models.graph import Follow, HandleHistory
from app.models.user import User
from app.schemas.auth import UserOut
from app.schemas.onboarding import HandleAvailability, OnboardingRequest, SuggestedUser

router = APIRouter(prefix="/v1", tags=["onboarding"])

_SUGGESTED_MAX = 25


def _handle_owner_id(db: Session, handle: str) -> tuple[str, object | None] | None:
    """Return `("user"|"history", owner_id)` if `handle` is spoken for, else
    None. Checks both the live column and the released-handle history."""
    live = db.scalar(select(User.id).where(User.profile_handle == handle))
    if live is not None:
        return ("user", live)
    historic = db.scalar(select(HandleHistory.user_id).where(HandleHistory.handle == handle))
    if historic is not None:
        return ("history", historic)
    return None


@router.get("/users/handle-available", response_model=HandleAvailability)
def handle_available(
    handle: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
) -> HandleAvailability:
    normalized = normalize_handle(handle)
    try:
        normalized = validate_handle(handle)
    except InvalidHandleError as exc:
        return HandleAvailability(available=False, normalized=normalized, reason=str(exc))

    if _handle_owner_id(db, normalized) is not None:
        return HandleAvailability(
            available=False,
            normalized=normalized,
            reason="That handle is already taken.",
        )
    return HandleAvailability(available=True, normalized=normalized, reason=None)


@router.get("/users/suggested", response_model=list[SuggestedUser])
def suggested_users(
    limit: int = Query(10, ge=1, le=_SUGGESTED_MAX),
    db: Session = Depends(get_db),
    viewer: User | None = Depends(get_current_user_optional),
) -> list[SuggestedUser]:
    """Public, active, non-guest profiles ordered by follower count, minus the
    caller and anyone they already follow."""
    follower_count = (
        select(Follow.followee_id, func.count().label("n")).group_by(Follow.followee_id).subquery()
    )
    stmt = (
        select(User, func.coalesce(follower_count.c.n, 0).label("follower_count"))
        .outerjoin(follower_count, follower_count.c.followee_id == User.id)
        .where(
            User.is_active.is_(True),
            User.is_guest.is_(False),
            User.is_profile_public.is_(True),
            User.profile_handle.is_not(None),
        )
        .order_by(func.coalesce(follower_count.c.n, 0).desc(), User.created_at.desc())
    )

    if viewer is not None:
        already_followed = select(Follow.followee_id).where(Follow.follower_id == viewer.id)
        stmt = stmt.where(User.id != viewer.id, User.id.not_in(already_followed))

    rows = db.execute(stmt.limit(limit)).all()
    return [
        SuggestedUser(
            id=user.id,
            profile_handle=user.profile_handle,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            affiliation=user.affiliation,
            follower_count=count,
        )
        for user, count in rows
    ]


@router.post("/users/me/onboarding", response_model=UserOut)
def complete_onboarding(
    payload: OnboardingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_full_user),
) -> User:
    try:
        handle = validate_handle(payload.handle)
    except InvalidHandleError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # The handle is permanent once onboarding has set it. Re-running this
    # endpoint may still update the display name / interests, but it can't be
    # used as a back door to rename a profile.
    if (
        current_user.onboarded_at is not None
        and current_user.profile_handle
        and handle != current_user.profile_handle
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your handle is permanent and can't be changed.",
        )

    owner = _handle_owner_id(db, handle)
    if owner is not None and str(owner[1]) != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That handle is already taken.",
        )

    previous_handle = current_user.profile_handle
    if previous_handle and previous_handle != handle:
        # Preserve the old handle so `/u/<old>` can redirect, and so it's
        # never re-issued to someone else.
        already_recorded = db.scalar(
            select(HandleHistory.id).where(HandleHistory.handle == previous_handle)
        )
        if already_recorded is None:
            db.add(HandleHistory(handle=previous_handle, user_id=current_user.id))

    current_user.profile_handle = handle
    current_user.display_name = payload.display_name
    current_user.research_interests = [i.strip() for i in payload.interests if i.strip()]
    current_user.is_profile_public = payload.is_profile_public
    current_user.onboarded_at = datetime.now(UTC)
    db.add(current_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That handle is already taken."
        ) from exc
    db.refresh(current_user)
    return current_user
