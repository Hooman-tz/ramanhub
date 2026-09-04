"""Shared public-community policy and serialization helpers."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.models.social import Notification, NotificationPreference
from app.models.user import User


def canonical_url(path: str) -> str | None:
    """Return an externally shareable URL only when a public domain is configured."""
    base_url = settings.PUBLIC_APP_URL.rstrip("/")
    return f"{base_url}{path}" if base_url else None


def public_profile_predicates() -> list[Any]:
    """The definition of "a profile a stranger is allowed to find".

    `is_profile_public` server-defaults to false, so this is opt-in: a user
    appears here only if they chose to publish a profile. That is what makes
    searching people acceptable at all — the result set is the set of pages
    already readable at `/profiles/{handle}`, not the user table.

    Shared by `/users/suggested` and `/v1/search/suggest` so the two cannot
    drift into disagreeing about who is public.
    """
    return [
        User.is_active.is_(True),
        User.is_guest.is_(False),
        User.is_profile_public.is_(True),
        User.profile_handle.is_not(None),
        # Not in the original `/users/suggested` predicate, but `public_author`
        # has always rendered a deleted user as "Former contributor" — so they
        # should not be reachable by name either.
        User.deleted_at.is_(None),
    ]


def public_author(user: User | None) -> dict[str, Any]:
    """Minimal attribution safe for public spectra, posts, and comments."""
    if user is None or not user.is_active or user.deleted_at is not None:
        return {
            "display_name": "Former contributor",
            "avatar_url": None,
            "orcid_id": None,
            "profile_path": None,
        }

    profile_path = (
        f"/u/{user.profile_handle}" if user.is_profile_public and user.profile_handle else None
    )
    return {
        "display_name": user.display_name or "Spectra Insight researcher",
        "avatar_url": user.avatar_url,
        "orcid_id": user.orcid_id if user.orcid_verified_at is not None else None,
        "profile_path": profile_path,
    }


def create_notification(
    db,
    *,
    user_id,
    kind: str,
    payload: dict[str, Any],
    preference: str = "comment_notifications",
) -> None:
    """Queue in-app notifications without allowing them to block core actions."""
    preferences = db.get(NotificationPreference, user_id)
    if preferences is not None and (
        not preferences.in_app_enabled or not getattr(preferences, preference)
    ):
        return
    db.add(Notification(user_id=user_id, kind=kind, payload=payload))
