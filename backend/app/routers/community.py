"""Posts, discussion, moderation reports, and in-app notifications."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user, get_current_moderator, get_current_user_optional
from app.community import create_notification, public_author
from app.db.session import get_db
from app.models.enums import SpectrumState
from app.models.publication import Publication
from app.models.social import (
    Comment,
    CommunityPost,
    CommunityPostSpectrum,
    Notification,
    NotificationPreference,
    PostReaction,
    Report,
)
from app.models.spectrum import Spectrum
from app.models.user import User
from app.processing.state_machine import require_owner_or_public
from app.ratelimit import rate_limit_posts, rate_limit_reports

router = APIRouter(prefix="/community", tags=["community"])

_MAX_POST_LENGTH = 10_000
_MAX_COMMENT_LENGTH = 2_000
_PUBLIC_STATUS = "visible"


class PostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=_MAX_POST_LENGTH)
    kind: Literal["announcement", "dataset"] = "announcement"
    spectrum_ids: list[UUID] = Field(min_length=1, max_length=24)
    publication_id: UUID | None = None


class PostUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    body: str | None = Field(default=None, min_length=1, max_length=_MAX_POST_LENGTH)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=_MAX_COMMENT_LENGTH)


class ReportCreate(BaseModel):
    target_type: Literal["spectrum", "post", "comment", "profile"]
    target_id: str = Field(min_length=1, max_length=80)
    reason: Literal["spam", "harassment", "privacy", "copyright", "misinformation", "other"]
    detail: str | None = Field(default=None, max_length=2_000)


class ReportResolution(BaseModel):
    action: Literal["dismiss", "hide"]
    note: str | None = Field(default=None, max_length=2_000)


class NotificationPreferencesUpdate(BaseModel):
    in_app_enabled: bool | None = None
    comment_notifications: bool | None = None
    moderation_notifications: bool | None = None


def _post_or_404(post_id: UUID, user: User | None, db: Session) -> CommunityPost:
    post = db.get(CommunityPost, post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    is_owner = user is not None and post.owner_id == user.id
    if (post.moderation_status != _PUBLIC_STATUS or post.deleted_at is not None) and not is_owner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not is_owner:
        visible_link = db.scalar(
            select(CommunityPostSpectrum.id)
            .join(Spectrum, Spectrum.id == CommunityPostSpectrum.spectrum_id)
            .where(
                CommunityPostSpectrum.post_id == post.id,
                Spectrum.state == SpectrumState.published,
                Spectrum.moderation_status == _PUBLIC_STATUS,
            )
            .limit(1)
        )
        if visible_link is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return post


def _post_payload(post: CommunityPost, user: User | None, db: Session) -> dict:
    author = db.get(User, post.owner_id)
    spectrum_rows = (
        db.query(Spectrum)
        .join(CommunityPostSpectrum, CommunityPostSpectrum.spectrum_id == Spectrum.id)
        .filter(
            CommunityPostSpectrum.post_id == post.id,
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == _PUBLIC_STATUS,
        )
        .all()
    )
    reaction_count = db.scalar(
        select(func.count()).select_from(PostReaction).where(PostReaction.post_id == post.id)
    ) or 0
    comment_count = db.scalar(
        select(func.count())
        .select_from(Comment)
        .where(
            Comment.post_id == post.id,
            Comment.moderation_status == _PUBLIC_STATUS,
            Comment.deleted_at.is_(None),
        )
    ) or 0
    reacted_by_me = (
        user is not None
        and db.scalar(
            select(PostReaction).where(
                PostReaction.post_id == post.id, PostReaction.user_id == user.id
            )
        )
        is not None
    )
    return {
        "id": str(post.id),
        "kind": post.kind,
        "title": post.title,
        "body": post.body,
        "author": public_author(author),
        "publication_id": str(post.publication_id) if post.publication_id else None,
        "spectrum_ids": [str(spectrum.id) for spectrum in spectrum_rows],
        "spectra": [
            {"id": str(spectrum.id), "title": spectrum.title, "modality": spectrum.modality.value}
            for spectrum in spectrum_rows
        ],
        "reaction_count": reaction_count,
        "reacted_by_me": reacted_by_me,
        "comment_count": comment_count,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
        "canonical_path": f"/community/posts/{post.id}",
    }


def _comment_payload(comment: Comment, db: Session) -> dict:
    return {
        "id": comment.id,
        "body": comment.body,
        "created_at": comment.created_at,
        "author": public_author(db.get(User, comment.user_id)),
    }


@router.post("/posts", status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_posts),
) -> dict:
    spectrum_ids = list(dict.fromkeys(payload.spectrum_ids))
    spectra = db.query(Spectrum).filter(Spectrum.id.in_(spectrum_ids)).all()
    if len(spectra) != len(spectrum_ids) or any(
        spectrum.owner_id != user.id or spectrum.moderation_status != _PUBLIC_STATUS
        for spectrum in spectra
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Posts may reference only your visible published spectra.",
        )
    for spectrum in spectra:
        require_owner_or_public(spectrum, None)
    publication = db.get(Publication, payload.publication_id) if payload.publication_id else None
    if payload.publication_id and publication is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Publication not found")
    if publication is not None and not any(spectrum.publication_id == publication.id for spectrum in spectra):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The selected publication must be attached to a linked spectrum.",
        )
    post = CommunityPost(
        owner_id=user.id,
        publication_id=payload.publication_id,
        kind=payload.kind,
        title=payload.title.strip(),
        body=payload.body.strip(),
    )
    db.add(post)
    db.flush()
    db.add_all(
        [CommunityPostSpectrum(post_id=post.id, spectrum_id=spectrum.id) for spectrum in spectra]
    )
    db.commit()
    db.refresh(post)
    return _post_payload(post, user, db)


@router.get("/posts")
def list_posts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[dict]:
    rows = (
        db.query(CommunityPost)
        .join(User, User.id == CommunityPost.owner_id)
        .join(CommunityPostSpectrum, CommunityPostSpectrum.post_id == CommunityPost.id)
        .join(Spectrum, Spectrum.id == CommunityPostSpectrum.spectrum_id)
        .filter(
            CommunityPost.moderation_status == _PUBLIC_STATUS,
            CommunityPost.deleted_at.is_(None),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == _PUBLIC_STATUS,
        )
        .distinct()
        .order_by(CommunityPost.created_at.desc(), CommunityPost.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_post_payload(post, user, db) for post in rows]


@router.get("/posts/{post_id}")
def get_post(
    post_id: UUID,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> dict:
    return _post_payload(_post_or_404(post_id, user, db), user, db)


@router.patch("/posts/{post_id}")
def update_post(
    post_id: UUID,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> dict:
    post = _post_or_404(post_id, user, db)
    if post.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if payload.title is not None:
        post.title = payload.title.strip()
    if payload.body is not None:
        post.body = payload.body.strip()
    db.add(post)
    db.commit()
    db.refresh(post)
    return _post_payload(post, user, db)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> None:
    post = _post_or_404(post_id, user, db)
    if post.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    post.moderation_status = "hidden"
    post.deleted_at = datetime.now(UTC)
    db.add(post)
    db.commit()


@router.post("/posts/{post_id}/reactions")
def toggle_post_reaction(
    post_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> dict:
    post = _post_or_404(post_id, user, db)
    try:
        with db.begin_nested():
            db.add(PostReaction(post_id=post.id, user_id=user.id))
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(PostReaction).where(PostReaction.post_id == post.id, PostReaction.user_id == user.id)
        )
        if existing is not None:
            db.delete(existing)
            db.commit()
        return {"reacted": False, "count": _post_payload(post, user, db)["reaction_count"]}
    if post.owner_id != user.id:
        create_notification(
            db,
            user_id=post.owner_id,
            kind="post_reaction",
            payload={"post_id": str(post.id), "actor": public_author(user)},
        )
    db.commit()
    return {"reacted": True, "count": _post_payload(post, user, db)["reaction_count"]}


@router.get("/posts/{post_id}/comments")
def list_post_comments(
    post_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
) -> list[dict]:
    post = _post_or_404(post_id, user, db)
    rows = (
        db.query(Comment)
        .filter(
            Comment.post_id == post.id,
            Comment.moderation_status == _PUBLIC_STATUS,
            Comment.deleted_at.is_(None),
        )
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_comment_payload(comment, db) for comment in rows]


@router.post("/posts/{post_id}/comments", status_code=status.HTTP_201_CREATED)
def post_comment(
    post_id: UUID,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_posts),
) -> dict:
    post = _post_or_404(post_id, user, db)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Comment body cannot be blank")
    comment = Comment(post_id=post.id, user_id=user.id, body=body)
    db.add(comment)
    if post.owner_id != user.id:
        create_notification(
            db,
            user_id=post.owner_id,
            kind="post_comment",
            payload={"post_id": str(post.id), "comment_id": None, "actor": public_author(user)},
        )
    db.commit()
    db.refresh(comment)
    return _comment_payload(comment, db)


def _target_owner(target_type: str, target_id: str, db: Session) -> tuple[object, User | None]:
    if target_type == "post":
        target = db.get(CommunityPost, UUID(target_id))
        owner = db.get(User, target.owner_id) if target else None
    elif target_type == "comment":
        target = db.get(Comment, int(target_id))
        owner = db.get(User, target.user_id) if target else None
    elif target_type == "spectrum":
        target = db.get(Spectrum, UUID(target_id))
        if target is not None:
            require_owner_or_public(target, None)
        owner = db.get(User, target.owner_id) if target else None
    else:
        target = db.query(User).filter(User.profile_handle == target_id.lower()).one_or_none()
        owner = target
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return target, owner


@router.post("/reports", status_code=status.HTTP_201_CREATED)
def create_report(
    payload: ReportCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_reports),
) -> dict:
    target, _owner = _target_owner(payload.target_type, payload.target_id, db)
    if getattr(target, "owner_id", getattr(target, "user_id", None)) == user.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="You cannot report your own content")
    report = Report(
        reporter_id=user.id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        reason=payload.reason,
        detail=payload.detail.strip() if payload.detail else None,
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already reported this item") from exc
    db.refresh(report)
    return {"id": str(report.id), "status": report.status}


@router.get("/moderation/reports")
def list_reports(
    status_filter: Literal["open", "dismissed", "resolved"] = "open",
    db: Session = Depends(get_db),
    _: User = Depends(get_current_moderator),
) -> list[dict]:
    rows = (
        db.query(Report)
        .filter(Report.status == status_filter)
        .order_by(Report.created_at.asc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": str(report.id),
            "target_type": report.target_type,
            "target_id": report.target_id,
            "reason": report.reason,
            "detail": report.detail,
            "status": report.status,
            "created_at": report.created_at,
        }
        for report in rows
    ]


@router.patch("/moderation/reports/{report_id}")
def resolve_report(
    report_id: UUID,
    payload: ReportResolution,
    db: Session = Depends(get_db),
    moderator: User = Depends(get_current_moderator),
) -> dict:
    report = db.get(Report, report_id)
    if report is None or report.status != "open":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    target, owner = _target_owner(report.target_type, report.target_id, db)
    now = datetime.now(UTC)
    if payload.action == "hide":
        if isinstance(target, (Comment, CommunityPost)):
            target.moderation_status = "hidden"
            target.deleted_at = now
        elif isinstance(target, Spectrum):
            target.moderation_status = "hidden"
        elif isinstance(target, User):
            target.is_profile_public = False
        if owner is not None and owner.id != moderator.id:
            create_notification(
                db,
                user_id=owner.id,
                kind="moderation_action",
                payload={"target_type": report.target_type, "target_id": report.target_id, "action": "hidden"},
                preference="moderation_notifications",
            )
    report.status = "resolved" if payload.action == "hide" else "dismissed"
    report.moderator_id = moderator.id
    report.resolution_note = payload.note.strip() if payload.note else None
    report.resolved_at = now
    create_notification(
        db,
        user_id=report.reporter_id,
        kind="report_resolved",
        payload={"report_id": str(report.id), "action": payload.action},
        preference="moderation_notifications",
    )
    db.add(report)
    db.commit()
    return {"id": str(report.id), "status": report.status}


@router.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> list[dict]:
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    rows = query.order_by(Notification.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(notification.id),
            "kind": notification.kind,
            "payload": notification.payload,
            "read_at": notification.read_at,
            "created_at": notification.created_at,
        }
        for notification in rows
    ]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> dict:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    notification.read_at = datetime.now(UTC)
    db.add(notification)
    db.commit()
    return {"id": str(notification.id), "read_at": notification.read_at}


@router.get("/notification-preferences")
def get_notification_preferences(
    db: Session = Depends(get_db), user: User = Depends(get_current_full_user)
) -> dict:
    preferences = db.get(NotificationPreference, user.id)
    if preferences is None:
        preferences = NotificationPreference(user_id=user.id)
        db.add(preferences)
        db.commit()
        db.refresh(preferences)
    return {
        "in_app_enabled": preferences.in_app_enabled,
        "comment_notifications": preferences.comment_notifications,
        "moderation_notifications": preferences.moderation_notifications,
    }


@router.patch("/notification-preferences")
def update_notification_preferences(
    payload: NotificationPreferencesUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> dict:
    preferences = db.get(NotificationPreference, user.id) or NotificationPreference(user_id=user.id)
    for field in payload.model_fields_set:
        setattr(preferences, field, getattr(payload, field))
    db.add(preferences)
    db.commit()
    return {
        "in_app_enabled": preferences.in_app_enabled,
        "comment_notifications": preferences.comment_notifications,
        "moderation_notifications": preferences.moderation_notifications,
    }