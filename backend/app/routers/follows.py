"""Following. Mounted with no prefix — `/users/{handle}/follow`,
`/users/{handle}/followers`, `/users/{handle}/following`.

Asymmetric by design: no request, no approval, no notification. See
`app.models.graph` for why the symmetric relation is derived from
co-authorship instead of being a second table.

Guests cannot follow (`get_current_full_user`), which matters more here than
for votes: a follower count is a public number people compare, so letting
throwaway guest sessions inflate it would make it meaningless immediately.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user_optional
from app.db.session import get_db
from app.handles import normalize_handle
from app.models.graph import Follow
from app.models.user import User
from app.ratelimit import rate_limit_follows

router = APIRouter(tags=["follows"])


class FollowToggleResponse(BaseModel):
    following: bool
    follower_count: int


class FollowUser(BaseModel):
    """Deliberately the same minimal identity shape `feed._author()` returns —
    a follower list is a list of bylines, and having two different "small
    user" DTOs is how they drift."""

    id: str
    handle: str | None
    display_name: str | None
    avatar_url: str | None
    affiliation: str | None


def _user_by_handle_or_404(handle: str, db: Session) -> User:
    user = db.scalar(select(User).where(User.profile_handle == normalize_handle(handle)))
    # Same 404-not-403 rule as everywhere else, and guests have no public
    # presence at all — so a guest handle is indistinguishable from a
    # nonexistent one.
    if user is None or not user.is_active or user.is_guest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


def _follower_count(user_id, db: Session) -> int:
    return (
        db.scalar(select(func.count()).select_from(Follow).where(Follow.followee_id == user_id))
        or 0
    )


def _as_follow_user(user: User) -> FollowUser:
    return FollowUser(
        id=str(user.id),
        handle=user.profile_handle,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        affiliation=user.affiliation,
    )


@router.post("/users/{handle}/follow", response_model=FollowToggleResponse)
def toggle_follow(
    handle: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_follows),
) -> FollowToggleResponse:
    """Toggle. Insert first and treat the unique-constraint violation as
    "unfollow", the same race-safe ordering `routers.votes` uses — a
    check-then-insert would let two concurrent clicks both insert."""
    target = _user_by_handle_or_404(handle, db)

    if target.id == user.id:
        # The DB CHECK would catch this anyway; a 400 explains it.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot follow yourself"
        )

    try:
        with db.begin_nested():
            db.add(Follow(follower_id=user.id, followee_id=target.id))
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Follow).where(
                Follow.follower_id == user.id, Follow.followee_id == target.id
            )
        )
        if existing is not None:
            db.delete(existing)
            db.commit()
        return FollowToggleResponse(following=False, follower_count=_follower_count(target.id, db))

    db.commit()
    return FollowToggleResponse(following=True, follower_count=_follower_count(target.id, db))


@router.get("/users/{handle}/followers", response_model=list[FollowUser])
def list_followers(
    handle: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[FollowUser]:
    target = _user_by_handle_or_404(handle, db)
    rows = db.scalars(
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.followee_id == target.id)
        .order_by(Follow.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_as_follow_user(u) for u in rows]


@router.get("/users/{handle}/following", response_model=list[FollowUser])
def list_following(
    handle: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[FollowUser]:
    target = _user_by_handle_or_404(handle, db)
    rows = db.scalars(
        select(User)
        .join(Follow, Follow.followee_id == User.id)
        .where(Follow.follower_id == target.id)
        .order_by(Follow.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_as_follow_user(u) for u in rows]


@router.get("/users/{handle}/follow", response_model=dict)
def follow_status(
    handle: str,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    """Whether the caller follows this person, for rendering the button in
    the right state on first paint rather than after a flash."""
    target = _user_by_handle_or_404(handle, db)
    following = False
    if user is not None:
        following = (
            db.scalar(
                select(func.count())
                .select_from(Follow)
                .where(Follow.follower_id == user.id, Follow.followee_id == target.id)
            )
            or 0
        ) > 0
    return {"following": following, "follower_count": _follower_count(target.id, db)}
