"""User profile endpoints. Mounted at prefix `/users`.

Two distinct surfaces here, and the split is deliberate:

- `/users/me` — the caller's own record, including `email`. Authenticated.
- `/users/by-handle/{handle}` — a contributor's PUBLIC profile, served to
  anyone. Returns `PublicProfileOut`, which has no `email` field at all, so
  a field added to `UserOut` can never leak onto a public page by default.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user
from app.db.session import get_db
from app.models.handles import normalize_handle
from app.models.user import User
from app.profile_stats import compute_profile_stats
from app.schemas.auth import PublicProfileOut, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserOut)
def patch_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_full_user),
    db: Session = Depends(get_db),
) -> User:
    if payload.display_name is not None:
        current_user.display_name = payload.display_name
    if payload.orcid_id is not None:
        current_user.orcid_id = payload.orcid_id
    if payload.affiliation is not None:
        current_user.affiliation = payload.affiliation
    if payload.bio is not None:
        current_user.bio = payload.bio
    if payload.handle is not None and payload.handle != current_user.handle:
        # Format/reserved-word validation already happened in UserUpdate;
        # this is the uniqueness check, which needs the database.
        taken = db.execute(
            select(User.id).where(User.handle == payload.handle, User.id != current_user.id)
        ).first()
        if taken is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"The handle '{payload.handle}' is already taken.",
            )
        current_user.handle = payload.handle

    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/by-handle/{handle}", response_model=PublicProfileOut)
def get_public_profile(handle: str, db: Session = Depends(get_db)) -> PublicProfileOut:
    """A contributor's public profile. No auth required — this is what a
    DOI or a citation points at.

    Counts cover PUBLISHED work only. Including drafts would leak how much
    unpublished work someone has, which is exactly the kind of thing the
    draft/published split exists to keep private.

    The full set of engagement figures is computed in `app.profile_stats`;
    that module documents what each one counts and what it excludes.
    """
    user = db.execute(
        select(User).where(User.handle == normalize_handle(handle))
    ).scalar_one_or_none()
    if user is None or not user.is_active or user.is_guest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    stats = compute_profile_stats(user.id, db)

    profile = PublicProfileOut.model_validate(user)
    # Assigned after validation because `User` carries none of these as
    # attributes — they are aggregates, not columns.
    profile.spectrum_count = stats.spectra_published
    profile.finding_count = stats.findings_published
    profile.followers = stats.followers
    profile.following = stats.following
    profile.doi_linked = stats.doi_linked
    profile.votes_received = stats.votes_received
    profile.shares_received = stats.shares_received
    profile.comments_written = stats.comments_written
    profile.reuse_findings = stats.reuse_findings
    profile.reuse_groups = stats.reuse_groups
    # Always False today: there is no ORCID OAuth flow, so no iD has actually
    # been verified. The field exists so the UI has something to branch on
    # the day one ships, and so nothing renders a badge in the meantime.
    profile.orcid_verified = False
    return profile
