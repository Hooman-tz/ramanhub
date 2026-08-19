"""Pydantic schemas for auth/user/license responses."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

ORCID_REGEX = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None = None
    avatar_url: str | None = None
    orcid_id: str | None = None
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    """Body for PATCH /users/me. All fields optional (partial update)."""

    display_name: str | None = None
    orcid_id: str | None = None

    @field_validator("orcid_id")
    @classmethod
    def _validate_orcid(cls, v: str | None) -> str | None:
        if v is not None and not ORCID_REGEX.match(v):
            raise ValueError(
                "orcid_id must match the standard ORCID iD format: ####-####-####-###X"
            )
        return v


class LicenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    url: str
    is_default: bool
