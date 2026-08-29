"""Schemas for the first-run onboarding flow (M3c)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class HandleAvailability(BaseModel):
    available: bool
    normalized: str
    reason: str | None = None


class SuggestedUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    profile_handle: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    affiliation: str | None = None
    follower_count: int = 0


class OnboardingRequest(BaseModel):
    handle: str = Field(min_length=1, max_length=30)
    display_name: str = Field(min_length=1, max_length=120)
    # Maps onto `User.research_interests` (the column already exists); the
    # request field is called `interests` to match the client contract.
    interests: list[str] = Field(default_factory=list, max_length=12)
    is_profile_public: bool = True
