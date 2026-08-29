"""Module 4b: comments on spectra and on Findings, with threaded replies.
Mounted with no prefix — `/spectra/{spectrum_id}/comments` and
`/findings/{finding_id}/comments`.

Both targets share the `comments` table; see `app.models.social` for why,
and note that each route filters on its own target column, which is only
sound because the CHECK constraint guarantees exactly one is set.

Reply depth is capped at one level. Deeply nested threads turn a scientific
discussion into an unreadable tree, and the cap can't be expressed as a
self-referencing foreign key, so it's enforced here.

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
    spectrum_id: UUID | None = None
    finding_id: UUID | None = None
    parent_id: int | None = None
    body: str
    created_at: datetime
    author: dict


def _get_visible_spectrum_or_404(spectrum_id: UUID, user: User | None, db: Session) -> Spectrum:
    spectrum = db.get(Spectrum, spectrum_id)
    if spectrum is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_owner_or_public(spectrum, user)
    return spectrum


def _get_visible_finding_or_404(finding_id: UUID, user: User | None, db: Session) -> Finding:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    require_finding_readable(finding, user)
    return finding


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent comment not found")
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


def _serialize_comment(comment: Comment, db: Session) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        spectrum_id=comment.spectrum_id,
        finding_id=comment.finding_id,
        parent_id=comment.parent_id,
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

    _validate_parent(body.parent_id, db, spectrum_id=spectrum.id)

    comment = Comment(
        spectrum_id=spectrum.id, user_id=user.id, body=stripped, parent_id=body.parent_id
    )
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
    db.flush()
    if finding.owner_id != user.id:
        create_notification(
            db,
            user_id=finding.owner_id,
            kind="finding_comment",
            payload={
                "finding_id": str(finding.id),
                "comment_id": comment.id,
                "actor": public_author(user),
            },
        )
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
        .where(
            Comment.finding_id == finding.id,
            Comment.moderation_status == "visible",
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [_serialize_comment(row, db) for row in rows]
