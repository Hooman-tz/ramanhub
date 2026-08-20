"""Google OAuth login/callback/logout. Mounted at prefix `/auth`."""
from __future__ import annotations

import hmac
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import google_oauth
from app.auth.deps import SESSION_COOKIE_NAME, get_current_user_optional
from app.auth.jwt import encode_session_token
from app.config import settings
from app.db.session import get_db
from app.logging_config import log_event
from app.models.processing_ledger import ProcessingLedger
from app.models.processing_routine import ProcessingRoutine
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.ratelimit import rate_limit_login
from app.schemas.auth import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _cookie_secure() -> bool:
    # Allow non-Secure cookies in local dev (plain http://localhost), require
    # Secure everywhere else.
    return settings.ENVIRONMENT != "development"


def migrate_guest_data(guest: User, target: User, db: Session) -> int:
    """Reassign everything a guest session created to `target`, so "sign in
    to keep your work" is literal. Returns the number of rows moved. The
    guest row itself is deactivated (not deleted) so its id stays valid in
    any logs/history. Commit is left to the caller."""
    moved = 0
    for model, column in (
        (RawFile, RawFile.owner_id),
        (Spectrum, Spectrum.owner_id),
        (ProcessingRoutine, ProcessingRoutine.owner_id),
        (ProcessingLedger, ProcessingLedger.created_by),
    ):
        moved += (
            db.query(model)
            .filter(column == guest.id)
            .update({column: target.id}, synchronize_session=False)
        )
    guest.is_active = False
    db.add(guest)
    return moved


@router.post("/guest", response_model=UserOut)
async def start_guest_session(
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_login),
) -> JSONResponse:
    """Mint a guest session: a real (is_guest) User row plus the same session
    cookie the OAuth flow issues, so every downstream ownership check works
    unchanged. Guests can upload and use the processing tools; publishing,
    votes, comments, and profile linking are gated to full accounts
    (app.auth.deps.get_current_full_user). Signing in with Google later
    migrates the guest's work to the real account (see `callback`)."""
    token = uuid.uuid4().hex
    guest = User(
        google_sub=f"guest:{token}",
        # email is NOT NULL + unique; .invalid is the RFC 2606 reserved TLD,
        # so this can never collide with a real address.
        email=f"guest-{token}@guest.invalid",
        display_name="Guest",
        is_guest=True,
    )
    db.add(guest)
    db.commit()
    db.refresh(guest)

    log_event(logger, "auth.guest.created", user_id=str(guest.id))

    response = JSONResponse(UserOut.model_validate(guest).model_dump(mode="json"))
    response.set_cookie(
        SESSION_COOKIE_NAME,
        encode_session_token(guest),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        max_age=settings.JWT_EXPIRES_HOURS * 3600,
    )
    return response


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
    # A pre-existing session at callback time is how we notice "this browser
    # was a guest" and migrate that guest's work to the real account.
    prior_session: User | None = Depends(get_current_user_optional),
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

    if prior_session is not None and prior_session.is_guest and prior_session.id != user.id:
        moved = migrate_guest_data(prior_session, user, db)
        db.commit()
        log_event(
            logger,
            "auth.guest.migrated",
            guest_id=str(prior_session.id),
            user_id=str(user.id),
            rows_moved=moved,
        )

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
