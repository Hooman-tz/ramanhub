"""Proof-of-control ORCID link routes for existing full accounts."""
from __future__ import annotations

import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import orcid_oauth
from app.auth.cookies import clear_cookie, set_state_cookie
from app.auth.deps import get_current_full_user
from app.config import settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import ORCID_REGEX

router = APIRouter(prefix="/users/me/orcid", tags=["orcid"])


@router.get("/link")
def begin_orcid_link(user: User = Depends(get_current_full_user)) -> RedirectResponse:
    if not orcid_oauth.configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ORCID linking is not configured yet.",
        )
    state = orcid_oauth.generate_state()
    response = RedirectResponse(orcid_oauth.build_authorization_url(state), status_code=302)
    set_state_cookie(
        response,
        orcid_oauth.ORCID_STATE_COOKIE,
        orcid_oauth.encode_state_cookie(state, str(user.id)),
    )
    return response


@router.get("/callback")
async def complete_orcid_link(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    user: User = Depends(get_current_full_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if error or not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ORCID linking was not completed")
    saved_state = orcid_oauth.decode_state_cookie(request.cookies.get(orcid_oauth.ORCID_STATE_COOKIE))
    if (
        saved_state is None
        or not secrets.compare_digest(saved_state["state"], state)
        or saved_state["user_id"] != str(user.id)
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired ORCID link request")
    try:
        token_payload = await orcid_oauth.exchange_code(code)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="ORCID token exchange failed") from exc
    orcid_id = token_payload.get("orcid")
    if not isinstance(orcid_id, str) or not ORCID_REGEX.fullmatch(orcid_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ORCID did not return a valid identifier")
    linked_user = (
        db.query(User).filter(User.orcid_id == orcid_id, User.id != user.id).one_or_none()
    )
    if linked_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That ORCID iD is already linked to another account.",
        )
    user.orcid_id = orcid_id
    user.orcid_verified_at = datetime.now(UTC)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That ORCID iD is already linked to another account.",
        ) from exc
    response = RedirectResponse(f"{settings.FRONTEND_URL.rstrip('/')}/account?orcid=linked", status_code=302)
    clear_cookie(response, orcid_oauth.ORCID_STATE_COOKIE)
    return response
