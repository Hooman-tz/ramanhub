"""Pydantic schemas for auth/user/license responses."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

ORCID_REGEX = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    orcid_id: str | None = None
    orcid_verified_at: datetime | None = None
    profile_handle: str | None = None
    bio: str | None = None
    affiliation: str | None = None
    research_interests: list[str] | None = None
    is_profile_public: bool = False
    is_moderator: bool = False
    deleted_at: datetime | None = None
    is_active: bool
    is_guest: bool = False
    onboarded_at: datetime | None = None
    created_at: datetime


class UserUpdate(BaseModel):
    """Body for PATCH /users/me. All fields optional (partial update)."""

    display_name: str | None = None
    orcid_id: str | None = None
    profile_handle: str | None = Field(default=None, min_length=3, max_length=64)
    bio: str | None = Field(default=None, max_length=2000)
    affiliation: str | None = Field(default=None, max_length=240)
    research_interests: list[str] | None = Field(default=None, max_length=12)
    is_profile_public: bool | None = None

    @field_validator("orcid_id")
    @classmethod
    def _validate_orcid(cls, v: str | None) -> str | None:
        if v is not None and not ORCID_REGEX.match(v):
            raise ValueError(
                "orcid_id must match the standard ORCID iD format: ####-####-####-###X"
            )
        return v

    @field_validator("profile_handle")
    @classmethod
    def _validate_profile_handle(cls, v: str | None) -> str | None:
        if v is None:
            return None
        handle = v.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])?", handle):
            raise ValueError("profile_handle may use lowercase letters, numbers, and hyphens")
        return handle

    @field_validator("research_interests")
    @classmethod
    def _validate_research_interests(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [interest.strip() for interest in v if interest.strip()]
        if any(len(interest) > 80 for interest in cleaned):
            raise ValueError("research interests must be 80 characters or fewer")
        return cleaned


class LicenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    is_default: bool
