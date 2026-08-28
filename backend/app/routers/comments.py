"""Module 4b: comments on spectra. Mounted with no prefix — full routes are
`/spectra/{spectrum_id}/comments`.

Deliberately quarantined from core search/discovery, same as votes — see
`app.routers.votes` and `app.routers.trending`.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user_optional
from app.community import create_notification, public_author
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
    body: str
    created_at: datetime
    author: dict


def _get_visible_spectrum_or_404(spectrum_id: UUID, user: User | None, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)
    return spectrum


def _serialize_comment(comment: Comment, db: Session) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        spectrum_id=comment.spectrum_id,
        body=comment.body,
        created_at=comment.created_at,
        author=public_author(db.get(User, comment.user_id)),
    )


@router.post(
    "/spectra/{spectrum_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_comment(
    spectrum_id: UUID,
    body: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_comments),
) -> CommentResponse:
    spectrum = _get_visible_spectrum_or_404(spectrum_id, user, db)

    stripped = body.body.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Comment body cannot be blank")

    comment = Comment(spectrum_id=spectrum.id, user_id=user.id, body=stripped)
    db.add(comment)
    db.flush()
    if spectrum.owner_id != user.id:
        create_notification(
            db,
            user_id=spectrum.owner_id,
            kind="spectrum_comment",
            payload={
                "spectrum_id": str(spectrum.id),
                "comment_id": comment.id,
                "actor": public_author(user),
            },
        )
    db.commit()
    db.refresh(comment)
    return _serialize_comment(comment, db)


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
        .where(
            Comment.spectrum_id == spectrum.id,
            Comment.moderation_status == "visible",
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_serialize_comment(row, db) for row in rows]


@router.delete("/spectra/{spectrum_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    spectrum_id: UUID,
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> None:
    spectrum = _get_visible_spectrum_or_404(spectrum_id, user, db)
    comment = db.get(Comment, comment_id)
    if comment is None or comment.spectrum_id != spectrum.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if comment.user_id != user.id and not user.is_moderator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    comment.moderation_status = "hidden"
    comment.deleted_at = datetime.now(UTC)
    db.add(comment)
    db.commit()
