"""Current-user profile endpoints. Mounted at prefix `/users`."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity import ActivitySummary, compute_activity
from app.auth.deps import get_current_full_user, get_current_user
from app.db.session import get_db
from app.handles import normalize_handle
from app.models.social import Comment, CommunityPost
from app.models.spectrum import Spectrum
from app.models.user import User
from app.models.user_llm_credential import UserLLMCredential
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
    previous_orcid_id = current_user.orcid_id
    if "orcid_id" in payload.model_fields_set and payload.orcid_id != previous_orcid_id:
        linked_user = (
            db.query(User)
            .filter(User.orcid_id == payload.orcid_id, User.id != current_user.id)
            .one_or_none()
            if payload.orcid_id
            else None
        )
        if linked_user is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That ORCID iD is already linked to another account.",
            )
    # `profile_handle` is deliberately NOT settable here: a handle is a stable,
    # citable identifier set once at onboarding. Changing it self-serve breaks
    # inbound links and citations. `PATCH /users/me` silently ignores it.
    for field in (
        "display_name",
        "orcid_id",
        "bio",
        "affiliation",
        "research_interests",
        "is_profile_public",
    ):
        if field in payload.model_fields_set:
            setattr(current_user, field, getattr(payload, field))
    if "orcid_id" in payload.model_fields_set and payload.orcid_id != previous_orcid_id:
        current_user.orcid_verified_at = None
        current_user.orcid_name = None

    db.add(current_user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That public profile handle is unavailable.",
        ) from exc
    db.refresh(current_user)
    return current_user


@router.get("/by-handle/{handle}", response_model=PublicProfileOut)
def get_public_profile(handle: str, db: Session = Depends(get_db)) -> PublicProfileOut:
    """A contributor's public profile. No auth required — this is what a DOI
    or a citation points at.

    Counts cover PUBLISHED work only. Including drafts would leak how much
    unpublished work someone has, which is exactly what the draft/published
    split exists to keep private. See `app.profile_stats` for what each
    engagement figure counts and deliberately excludes.
    """
    user = db.scalar(select(User).where(User.profile_handle == normalize_handle(handle)))
    if user is None or not user.is_active or user.is_guest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    stats = compute_profile_stats(user.id, db)

    profile = PublicProfileOut.model_validate(user)
    # Assigned after validation: `User` carries none of these as attributes —
    # they are aggregates, not columns.
    profile.spectrum_count = stats.spectrum_count
    profile.finding_count = stats.finding_count
    profile.followers = stats.followers
    profile.following = stats.following
    profile.doi_linked = stats.doi_linked
    profile.votes_received = stats.votes_received
    profile.shares_received = stats.shares_received
    profile.comments_written = stats.comments_written
    profile.reuse_findings = stats.reuse_findings
    profile.reuse_groups = stats.reuse_groups
    # Real ORCID OAuth landed in M3, so this is a genuine signal, not a
    # placeholder: `orcid_verified_at` is set only by the verified OAuth flow.
    profile.orcid_verified = user.orcid_verified_at is not None
    return profile


@router.get("/{handle}/activity", response_model=ActivitySummary)
def get_public_activity(
    handle: str,
    days: int = Query(365, ge=1, le=730),
    db: Session = Depends(get_db),
) -> ActivitySummary:
    """Per-day contribution counts plus streaks, for the profile chart.

    Public, and published-events-only — see `app.activity` for what each kind
    counts and why the series are kept separate rather than summed.
    """
    user = db.scalar(select(User).where(User.profile_handle == normalize_handle(handle)))
    if user is None or not user.is_active or user.is_guest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return compute_activity(user.id, db, days=days)


@router.get("/me/export")
def export_my_account(
    current_user: User = Depends(get_current_full_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return a portable account export without storage locations or raw bytes."""
    spectra = db.query(Spectrum).filter(Spectrum.owner_id == current_user.id).all()
    return {
        "profile": UserOut.model_validate(current_user).model_dump(mode="json"),
        "spectra": [
            {
                "id": str(spectrum.id),
                "title": spectrum.title,
                "description": spectrum.description,
                "state": spectrum.state.value,
                "doi": spectrum.doi,
                "license_id": spectrum.license_id,
                "confirmed_metadata": spectrum.confirmed_metadata,
                "published_at": spectrum.published_at,
                "created_at": spectrum.created_at,
            }
            for spectrum in spectra
        ],
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_account(
    current_user: User = Depends(get_current_full_user),
    db: Session = Depends(get_db),
) -> Response:
    """Anonymize an account while preserving published scientific provenance."""
    now = datetime.now(UTC)
    deleted_identifier = current_user.id.hex
    current_user.google_sub = f"deleted:{deleted_identifier}"
    current_user.email = f"deleted-{deleted_identifier}@deleted.invalid"
    current_user.display_name = None
    current_user.avatar_url = None
    current_user.orcid_id = None
    current_user.orcid_name = None
    current_user.orcid_verified_at = None
    current_user.bio = None
    current_user.affiliation = None
    current_user.research_interests = None
    current_user.is_profile_public = False
    current_user.is_active = False
    current_user.deleted_at = now
    db.query(CommunityPost).filter(CommunityPost.owner_id == current_user.id).update(
        {"moderation_status": "hidden", "deleted_at": now}, synchronize_session=False
    )
    db.query(Comment).filter(Comment.user_id == current_user.id).update(
        {"moderation_status": "hidden", "deleted_at": now}, synchronize_session=False
    )
    # This anonymizes rather than deletes the `users` row, so the credential
    # table's ON DELETE CASCADE never fires — the stored provider key has to
    # be dropped explicitly, or it would outlive the account that owns it.
    db.query(UserLLMCredential).filter(
        UserLLMCredential.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.add(current_user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
