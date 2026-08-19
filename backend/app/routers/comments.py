"""Module 4b: comments on spectra. Mounted with no prefix — full routes are
`/spectra/{spectrum_id}/comments`.

Deliberately quarantined from core search/discovery, same as votes — see
`app.routers.votes` and `app.routers.trending`.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.social import Comment
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_owner_or_public
from app.ratelimit import rate_limit_comments

router = APIRouter(tags=["comments"])

_MAX_COMMENT_LENGTH = 2000


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=_MAX_COMMENT_LENGTH)


class CommentResponse(BaseModel):
    id: int
    spectrum_id: UUID
    user_id: UUID
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


def _get_visible_spectrum_or_404(spectrum_id: UUID, user: User | None, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)
    return spectrum


@router.post(
    "/spectra/{spectrum_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_comment(
    spectrum_id: UUID,
    body: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    _: None = Depends(rate_limit_comments),
) -> CommentResponse:
    spectrum = _get_visible_spectrum_or_404(spectrum_id, user, db)

    stripped = body.body.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Comment body cannot be blank")

    comment = Comment(spectrum_id=spectrum.id, user_id=user.id, body=stripped)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return CommentResponse.model_validate(comment)


@router.get("/spectra/{spectrum_id}/comments", response_model=list[CommentResponse])
def list_comments(
    spectrum_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[CommentResponse]:
    spectrum = _get_visible_spectrum_or_404(spectrum_id, user, db)

    # Oldest-first: comments read like a conversation thread, so chronological
    # (ascending) order reads most naturally.
    rows = db.scalars(
        select(Comment)
        .where(Comment.spectrum_id == spectrum.id)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [CommentResponse.model_validate(row) for row in rows]
