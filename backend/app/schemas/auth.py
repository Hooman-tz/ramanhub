"""Pydantic schemas for auth/user/license responses."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.handles import InvalidHandleError, validate_handle

ORCID_REGEX = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

MAX_BIO_LENGTH = 1000
MAX_AFFILIATION_LENGTH = 200


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    handle: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    orcid_id: str | None = None
    affiliation: str | None = None
    bio: str | None = None
    is_active: bool
    is_guest: bool = False
    created_at: datetime


class PublicProfileOut(BaseModel):
    """A contributor's public profile — deliberately NOT `UserOut`.

    `UserOut` carries `email`, which is personal data collected via OAuth
    and must never appear on a page anyone can load. Keeping the public
    shape as a separate model means a field added to `UserOut` can't
    silently become public.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    handle: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    orcid_id: str | None = None
    affiliation: str | None = None
    bio: str | None = None
    created_at: datetime
    spectrum_count: int = 0
    finding_count: int = 0

    # Public engagement figures. See `app.profile_stats` for exactly what
    # each one counts and, more importantly, what it deliberately excludes
    # (drafts, and self-reuse).
    followers: int = 0
    following: int = 0
    doi_linked: int = 0
    votes_received: int = 0
    shares_received: int = 0
    comments_written: int = 0
    reuse_findings: int = 0
    reuse_groups: int = 0

    # ORCID is stored as unverified free text — there is no ORCID OAuth flow,
    # so anyone could enter anyone's iD. This flag exists so the UI can label
    # it "self-reported" rather than render a verification badge, which would
    # turn the field into an impersonation tool.
    orcid_verified: bool = False


class UserUpdate(BaseModel):
    """Body for PATCH /users/me. All fields optional (partial update)."""

    display_name: str | None = None
    orcid_id: str | None = None
    handle: str | None = None
    affiliation: str | None = None
    bio: str | None = None

    @field_validator("orcid_id")
    @classmethod
    def _validate_orcid(cls, v: str | None) -> str | None:
        if v is not None and not ORCID_REGEX.match(v):
            raise ValueError(
                "orcid_id must match the standard ORCID iD format: ####-####-####-###X"
            )
        return v

    @field_validator("handle")
    @classmethod
    def _validate_handle(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            return validate_handle(v)
        except InvalidHandleError as exc:
            # Re-raised as ValueError so FastAPI renders it as a 422 with
            # the human-readable message rather than a 500.
            raise ValueError(str(exc)) from exc

    @field_validator("bio")
    @classmethod
    def _validate_bio(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_BIO_LENGTH:
            raise ValueError(f"Bio must be {MAX_BIO_LENGTH} characters or fewer.")
        return v

    @field_validator("affiliation")
    @classmethod
    def _validate_affiliation(cls, v: str | None) -> str | None:
        if v is not None and len(v) > MAX_AFFILIATION_LENGTH:
            raise ValueError(
                f"Affiliation must be {MAX_AFFILIATION_LENGTH} characters or fewer."
            )
        return v


class LicenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    is_default: bool
