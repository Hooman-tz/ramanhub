"""Google OAuth login/callback/logout. Mounted at prefix `/auth`."""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import google_oauth
from app.auth.deps import SESSION_COOKIE_NAME
from app.auth.jwt import encode_session_token
from app.config import settings
from app.db.session import get_db
from app.logging_config import log_event
from app.models.user import User
from app.ratelimit import rate_limit_login

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _cookie_secure() -> bool:
    # Allow non-Secure cookies in local dev (plain http://localhost), require
    # Secure everywhere else.
    return settings.ENVIRONMENT != "development"


@router.get("/login")
async def login() -> RedirectResponse:
    """Redirect the browser to Google's consent screen, carrying CSRF
    `state`/OIDC `nonce` in a short-lived signed cookie."""
    state, nonce = google_oauth.generate_state_and_nonce()
    authorization_url = google_oauth.build_authorization_url(state, nonce)

    response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        google_oauth.OAUTH_STATE_COOKIE,
        google_oauth.encode_oauth_state_cookie(state, nonce),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=600,
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_login),
) -> RedirectResponse:
    """Exchange the authorization code, verify the ID token, upsert the User,
    issue an app session JWT cookie, and redirect back to the frontend."""
    if error:
        log_event(logger, "auth.login.failure", reason="oauth_error", detail=error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Google OAuth error: {error}"
        )
    if not code or not state:
        log_event(logger, "auth.login.failure", reason="missing_code_or_state")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state parameter"
        )

    cookie_value = request.cookies.get(google_oauth.OAUTH_STATE_COOKIE)
    stored = google_oauth.decode_oauth_state_cookie(cookie_value) if cookie_value else None
    if stored is None or not _constant_time_eq(stored["state"], state):
        log_event(logger, "auth.login.failure", reason="invalid_or_expired_state")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state"
        )

    tokens = await google_oauth.exchange_code_for_tokens(code)
    id_token = tokens.get("id_token")
    if not id_token:
        log_event(logger, "auth.login.failure", reason="missing_id_token")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google token response did not include an id_token",
        )

    try:
        claims = await google_oauth.verify_id_token(id_token, stored["nonce"])
    except ValueError as exc:
        log_event(logger, "auth.login.failure", reason="invalid_id_token")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    google_sub = claims.get("sub")
    if not google_sub:
        log_event(logger, "auth.login.failure", reason="missing_sub_claim")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Google ID token missing sub claim"
        )
    email = claims.get("email")
    name = claims.get("name")
    picture = claims.get("picture")

    user = db.query(User).filter(User.google_sub == google_sub).first()
    if user is None:
        user = User(google_sub=google_sub, email=email, display_name=name, avatar_url=picture)
        db.add(user)
    else:
        if email and user.email != email:
            user.email = email
        if name and user.display_name != name:
            user.display_name = name
        if picture and user.avatar_url != picture:
            user.avatar_url = picture
    db.commit()
    db.refresh(user)

    log_event(logger, "auth.login.success", user_id=str(user.id))

    session_token = encode_session_token(user)

    response = RedirectResponse(url=settings.FRONTEND_URL, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(google_oauth.OAUTH_STATE_COOKIE)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=settings.JWT_EXPIRES_HOURS * 3600,
    )
    return response


@router.post("/logout")
async def logout() -> JSONResponse:
    """Clear the `session` cookie."""
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
