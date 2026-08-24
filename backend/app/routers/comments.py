"""Module 4b: comments on spectra and on Findings, with threaded replies.
Mounted with no prefix — `/spectra/{spectrum_id}/comments` and
`/findings/{finding_id}/comments`.

Both targets share the `comments` table; see `app.models.social` for why,
and note that each route filters on its own target column, which is only
sound because the CHECK constraint guarantees exactly one is set.

Reply depth is capped at one level. Deeply nested threads turn a scientific
discussion into an unreadable tree, and the cap can't be expressed as a
self-referencing foreign key, so it's enforced here.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_user_optional
from app.db.session import get_db
from app.models.finding import Finding
from app.models.social import Comment
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_finding_readable, require_owner_or_public
from app.ratelimit import rate_limit_comments

router = APIRouter(tags=["comments"])

_MAX_COMMENT_LENGTH = 2000


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=_MAX_COMMENT_LENGTH)
    parent_id: int | None = None


class CommentResponse(BaseModel):
    id: int
    # Nullable now that a comment targets either a spectrum or a Finding.
    spectrum_id: UUID | None = None
    finding_id: UUID | None = None
    parent_id: int | None = None
    user_id: UUID
    body: str
    created_at: datetime
    # Denormalized for rendering: a comment list otherwise needs an N+1
    # user lookup per row just to show who wrote it.
    author_handle: str | None = None
    author_display_name: str | None = None

    model_config = {"from_attributes": True}


def _serialize_comment(comment: Comment, db: Session) -> CommentResponse:
    out = CommentResponse.model_validate(comment)
    author = db.get(User, comment.user_id)
    if author is not None:
        out.author_handle = author.handle
        out.author_display_name = author.display_name
    return out


def _validate_parent(parent_id: int | None, db: Session, **target) -> None:
    """A reply must point at a comment on the SAME target, and that comment
    must itself be top-level.

    The same-target check is the security-relevant half: without it, a reply
    could be attached to a comment on a private spectrum and then read back
    through a public Finding's comment list.
    """
    if parent_id is None:
        return
    parent = db.get(Comment, parent_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent comment not found")
    for column, value in target.items():
        if getattr(parent, column) != value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A reply must be on the same spectrum or finding as its parent.",
            )
    if parent.parent_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Replies can only be one level deep.",
        )


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
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_comments),
) -> CommentResponse:
    spectrum = _get_visible_spectrum_or_404(spectrum_id, user, db)

    stripped = body.body.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Comment body cannot be blank")

    _validate_parent(body.parent_id, db, spectrum_id=spectrum.id)

    comment = Comment(
        spectrum_id=spectrum.id, user_id=user.id, body=stripped, parent_id=body.parent_id
    )
    db.add(comment)
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
        .where(Comment.spectrum_id == spectrum.id)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_serialize_comment(row, db) for row in rows]


def _get_visible_finding_or_404(finding_id: UUID, user: User | None, db: Session) -> Finding:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_finding_readable(finding, user)
    return finding


@router.post(
    "/findings/{finding_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_finding_comment(
    finding_id: UUID,
    body: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_comments),
) -> CommentResponse:
    finding = _get_visible_finding_or_404(finding_id, user, db)

    stripped = body.body.strip()
    if not stripped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Comment body cannot be blank",
        )

    _validate_parent(body.parent_id, db, finding_id=finding.id)

    comment = Comment(
        finding_id=finding.id, user_id=user.id, body=stripped, parent_id=body.parent_id
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return _serialize_comment(comment, db)


@router.get("/findings/{finding_id}/comments", response_model=list[CommentResponse])
def list_finding_comments(
    finding_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[CommentResponse]:
    finding = _get_visible_finding_or_404(finding_id, user, db)

    rows = db.scalars(
        select(Comment)
        .where(Comment.finding_id == finding.id)
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_serialize_comment(row, db) for row in rows]
