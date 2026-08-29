"""Resolve an OAuth login to a local `User`, creating one if needed.

The single entry point every sign-in provider (Google, GitHub, ORCID) funnels
through. It owns the three-way decision: known identity -> its user; new
identity but a known email -> attach; otherwise -> brand-new account. Never
commits — the calling router owns the transaction (so guest-data migration in
the same request commits atomically with the account it migrates to).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.handles import assign_handle
from app.models.auth_identity import AuthIdentity
from app.models.user import User


def _derive_display_name(display_name: str | None, email: str | None, subject: str) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    if email and "@" in email:
        return email.split("@", 1)[0]
    return subject


def resolve_or_create_user(
    db: Session,
    *,
    provider: str,
    subject: str,
    email: str | None,
    display_name: str | None,
    avatar_url: str | None = None,
    orcid_id: str | None = None,
) -> User:
    """Return the `User` for `(provider, subject)`, creating the account and/or
    the `AuthIdentity` row as needed. Caller commits."""
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider,
            AuthIdentity.provider_subject == subject,
        )
    )
    if identity is not None:
        user = identity.user
        # Backfill fields the provider now supplies that we never had.
        if avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
        if display_name and not user.display_name:
            user.display_name = display_name.strip()
        if email and not identity.email:
            identity.email = email
        if provider == "orcid" and orcid_id and not user.orcid_id:
            user.orcid_id = orcid_id
        db.flush()
        return user

    # Legacy Google rows: accounts that predate `auth_identities` (or that
    # the backfill hasn't reached) are still keyed by `users.google_sub`.
    # Adopt such a row into an identity rather than duplicating the person.
    if provider == "google":
        legacy = db.scalar(select(User).where(User.google_sub == subject))
        if legacy is not None:
            db.add(
                AuthIdentity(
                    user_id=legacy.id,
                    provider="google",
                    provider_subject=subject,
                    email=email or legacy.email,
                )
            )
            if email and legacy.email != email:
                legacy.email = email
            if display_name and legacy.display_name != display_name.strip():
                legacy.display_name = display_name.strip()
            if avatar_url and legacy.avatar_url != avatar_url:
                legacy.avatar_url = avatar_url
            db.flush()
            return legacy

    # A new identity. If it carries an email we already know, link the two
    # rather than fragmenting one person's records across two accounts.
    if email:
        existing = db.scalar(
            select(User).where(User.email == email, User.is_guest.is_(False))
        )
        if existing is not None:
            db.add(
                AuthIdentity(
                    user_id=existing.id,
                    provider=provider,
                    provider_subject=subject,
                    email=email,
                )
            )
            if avatar_url and not existing.avatar_url:
                existing.avatar_url = avatar_url
            if provider == "orcid" and orcid_id and not existing.orcid_id:
                existing.orcid_id = orcid_id
            db.flush()
            return existing

    user = User(
        email=email,
        google_sub=None,
        display_name=_derive_display_name(display_name, email, subject),
        avatar_url=avatar_url,
        orcid_id=orcid_id if provider == "orcid" else None,
        is_guest=False,
    )
    db.add(user)
    db.flush()
    user.profile_handle = assign_handle(
        db, email or f"{subject}@{provider}.local", user.display_name
    )
    db.add(
        AuthIdentity(
            user_id=user.id,
            provider=provider,
            provider_subject=subject,
            email=email,
        )
    )
    db.flush()
    return user
