"""Read-only public researcher profiles."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.community import canonical_url, public_author
from app.db.session import get_db
from app.models.enums import SpectrumState
from app.models.spectrum import Spectrum
from app.models.user import User

router = APIRouter(tags=["profiles"])


class PublicProfileSpectrum(BaseModel):
    id: UUID
    title: str | None
    modality: str
    doi: str | None
    published_at: datetime | None


class PublicProfileResponse(BaseModel):
    handle: str
    display_name: str
    avatar_url: str | None
    orcid_id: str | None
    affiliation: str | None
    bio: str | None
    research_interests: list[str]
    joined_at: datetime
    canonical_path: str
    canonical_url: str | None
    spectra: list[PublicProfileSpectrum]


@router.get("/profiles/{handle}", response_model=PublicProfileResponse)
def get_public_profile(
    handle: str,
    limit: int = Query(default=24, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PublicProfileResponse:
    user = (
        db.query(User)
        .filter(
            User.profile_handle == handle.lower(),
            User.is_active.is_(True),
            User.is_profile_public.is_(True),
            User.deleted_at.is_(None),
        )
        .one_or_none()
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    spectra = (
        db.query(Spectrum)
        .filter(
            Spectrum.owner_id == user.id,
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == "visible",
        )
        .order_by(Spectrum.published_at.desc())
        .limit(limit)
        .all()
    )
    author = public_author(user)
    path = f"/profiles/{user.profile_handle}"
    return PublicProfileResponse(
        handle=user.profile_handle,
        display_name=author["display_name"],
        avatar_url=author["avatar_url"],
        orcid_id=author["orcid_id"],
        affiliation=user.affiliation,
        bio=user.bio,
        research_interests=user.research_interests or [],
        joined_at=user.created_at,
        canonical_path=path,
        canonical_url=canonical_url(path),
        spectra=[
            PublicProfileSpectrum(
                id=spectrum.id,
                title=spectrum.title,
                modality=spectrum.modality.value,
                doi=spectrum.doi,
                published_at=spectrum.published_at,
            )
            for spectrum in spectra
        ],
    )