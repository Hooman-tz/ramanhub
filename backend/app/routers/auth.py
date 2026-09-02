"""OAuth sign-in (Google, GitHub, ORCID), guest sessions, logout.
Mounted at prefix `/auth`.

All three OAuth providers funnel through `app.auth.identities.resolve_or_create_user`
so "sign in with a different provider" lands on the same account, and through
`app.auth.guest_migration.migrate_guest_data` so a guest's work follows them
into whatever account they sign into.
"""
from __future__ import annotations

import hmac
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import github_oauth, google_oauth, orcid_oauth
from app.auth.cookies import clear_cookie, set_session_cookie, set_state_cookie
from app.auth.deps import SESSION_COOKIE_NAME, get_current_user_optional
from app.auth.guest_migration import migrate_guest_data
from app.auth.identities import resolve_or_create_user
from app.auth.jwt import encode_session_token
from app.config import settings
from app.db.session import get_db
from app.logging_config import log_event
from app.models.user import User
from app.ratelimit import rate_limit_login
from app.schemas.auth import UserOut

# Re-exported for callers/tests that historically imported it from here.
__all__ = ["migrate_guest_data", "router"]

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def _issue_session(user: User) -> RedirectResponse:
    """Redirect to the frontend with the `session` cookie set for `user`."""
    response = RedirectResponse(url=settings.FRONTEND_URL, status_code=status.HTTP_302_FOUND)
    set_session_cookie(response, SESSION_COOKIE_NAME, encode_session_token(user))
    return response


def _maybe_migrate_guest(prior_session: User | None, user: User, db: Session) -> None:
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


@router.post("/guest", response_model=UserOut)
async def start_guest_session(
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_login),
) -> JSONResponse:
    """Mint a guest session: a real (is_guest) User row plus the same session
    cookie the OAuth flow issues, so every downstream ownership check works
    unchanged. Guests can upload and use the processing tools; publishing,
    votes, comments, and profile linking are gated to full accounts
    (app.auth.deps.get_current_full_user). Signing in later migrates the
    guest's work to the real account."""
    token = uuid.uuid4().hex
    guest = User(
        google_sub=f"guest:{token}",
        # email is unique; .invalid is the RFC 2606 reserved TLD, so this
        # can never collide with a real address.
        email=f"guest-{token}@guest.invalid",
        display_name="Guest",
        is_guest=True,
    )
    db.add(guest)
    db.commit()
    db.refresh(guest)

    log_event(logger, "auth.guest.created", user_id=str(guest.id))

    response = JSONResponse(UserOut.model_validate(guest).model_dump(mode="json"))
    set_session_cookie(response, SESSION_COOKIE_NAME, encode_session_token(guest))
    return response


@router.get("/session", response_model=UserOut | None)
def get_session_user(user: User | None = Depends(get_current_user_optional)) -> User | None:
    """Return the signed-in user or null, without treating public browsing as
    an authorization error. `/users/me` remains the strict private endpoint."""
    return user


@router.get("/dev-login")
async def dev_login(
    email: str = "demo@ramanhub.example",
    db: Session = Depends(get_db),
    prior_session: User | None = Depends(get_current_user_optional),
) -> RedirectResponse:
    """LOCAL DEV ONLY. Signs you in as a full (non-guest) account without an
    OAuth round trip, so the social write paths can be exercised before real
    provider secrets are configured. Returns 404 unless
    `ENVIRONMENT=development`; never reachable in staging/production."""
    if settings.ENVIRONMENT != "development":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    user = db.query(User).filter(User.email == email, User.is_guest.is_(False)).one_or_none()
    if user is None:
        user = User(email=email, display_name=email.split("@")[0], is_guest=False)
        db.add(user)
        db.flush()
    _maybe_migrate_guest(prior_session, user, db)
    db.commit()
    log_event(logger, "auth.dev_login", user_id=str(user.id))
    return _issue_session(user)


# --- Google ---------------------------------------------------------------


@router.get("/login")
async def login() -> RedirectResponse:
    """Redirect the browser to Google's consent screen, carrying CSRF
    `state`/OIDC `nonce` in a short-lived signed cookie."""
    state, nonce = google_oauth.generate_state_and_nonce()
    authorization_url = google_oauth.build_authorization_url(state, nonce)

    response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)
    set_state_cookie(response, google_oauth.OAUTH_STATE_COOKIE, google_oauth.encode_oauth_state_cookie(state, nonce))
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_login),
    prior_session: User | None = Depends(get_current_user_optional),
) -> RedirectResponse:
    """Exchange the authorization code, verify the ID token, resolve/create
    the User, issue an app session JWT cookie, and redirect to the frontend."""
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
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google ID token did not include a verified email address",
        )
    if claims.get("email_verified") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google must verify the email address before it can be used to sign in",
        )

    user = resolve_or_create_user(
        db,
        provider="google",
        subject=google_sub,
        email=email,
        display_name=name,
        avatar_url=picture,
    )
    db.commit()
    db.refresh(user)

    _maybe_migrate_guest(prior_session, user, db)

    log_event(logger, "auth.login.success", user_id=str(user.id), provider="google")

    response = _issue_session(user)
    clear_cookie(response, google_oauth.OAUTH_STATE_COOKIE)
    return response


# --- GitHub -------------------------------------------------------------


@router.get("/github/login")
async def github_login() -> RedirectResponse:
    if not github_oauth.configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GitHub sign-in is not configured.",
        )
    state = github_oauth.generate_state()
    response = RedirectResponse(
        url=github_oauth.build_authorization_url(state), status_code=status.HTTP_302_FOUND
    )
    set_state_cookie(response, github_oauth.STATE_COOKIE, github_oauth.encode_state_cookie(state))
    return response


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_login),
    prior_session: User | None = Depends(get_current_user_optional),
) -> RedirectResponse:
    if error:
        log_event(logger, "auth.login.failure", provider="github", reason="oauth_error", detail=error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"GitHub OAuth error: {error}"
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state parameter"
        )

    stored = github_oauth.decode_state_cookie(request.cookies.get(github_oauth.STATE_COOKIE))
    if stored is None or not _constant_time_eq(stored["state"], state):
        log_event(logger, "auth.login.failure", provider="github", reason="invalid_or_expired_state")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state"
        )

    try:
        token = await github_oauth.exchange_code(code)
        gh = await github_oauth.fetch_user(token)
        primary_email = await github_oauth.fetch_primary_email(token)
    except (httpx.HTTPError, ValueError) as exc:
        log_event(logger, "auth.login.failure", provider="github", reason="exchange_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub sign-in failed"
        ) from exc

    if not gh.get("id"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub did not return an account id"
        )

    user = resolve_or_create_user(
        db,
        provider="github",
        subject=str(gh["id"]),
        email=primary_email,
        display_name=gh.get("name") or gh.get("login"),
        avatar_url=gh.get("avatar_url"),
    )
    db.commit()
    db.refresh(user)

    _maybe_migrate_guest(prior_session, user, db)

    log_event(logger, "auth.login.success", user_id=str(user.id), provider="github")

    response = _issue_session(user)
    clear_cookie(response, github_oauth.STATE_COOKIE)
    return response


# --- ORCID sign-in (distinct from the linking flow in routers/orcid.py) ---


@router.get("/orcid/login")
async def orcid_login() -> RedirectResponse:
    if not orcid_oauth.configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ORCID sign-in is not configured.",
        )
    state = orcid_oauth.generate_state()
    response = RedirectResponse(
        url=orcid_oauth.build_login_authorization_url(state), status_code=status.HTTP_302_FOUND
    )
    set_state_cookie(response, orcid_oauth.LOGIN_STATE_COOKIE, orcid_oauth.encode_login_state_cookie(state))
    return response


@router.get("/orcid/callback")
async def orcid_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_login),
    prior_session: User | None = Depends(get_current_user_optional),
) -> RedirectResponse:
    if error:
        log_event(logger, "auth.login.failure", provider="orcid", reason="oauth_error", detail=error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"ORCID OAuth error: {error}"
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state parameter"
        )

    stored = orcid_oauth.decode_login_state_cookie(
        request.cookies.get(orcid_oauth.LOGIN_STATE_COOKIE)
    )
    if stored is None or not _constant_time_eq(stored["state"], state):
        log_event(logger, "auth.login.failure", provider="orcid", reason="invalid_or_expired_state")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OAuth state"
        )

    try:
        token = await orcid_oauth.exchange_code(
            code, redirect_uri=settings.ORCID_LOGIN_REDIRECT_URI
        )
    except httpx.HTTPError as exc:
        log_event(logger, "auth.login.failure", provider="orcid", reason="exchange_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ORCID sign-in failed"
        ) from exc

    identity = orcid_oauth.extract_identity(token)
    orcid_id = identity.get("orcid")
    if not orcid_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ORCID did not return an iD"
        )

    user = resolve_or_create_user(
        db,
        provider="orcid",
        subject=orcid_id,
        email=None,
        display_name=identity.get("name"),
        orcid_id=orcid_id,
    )
    db.commit()
    db.refresh(user)

    _maybe_migrate_guest(prior_session, user, db)

    log_event(logger, "auth.login.success", user_id=str(user.id), provider="orcid")

    response = _issue_session(user)
    clear_cookie(response, orcid_oauth.LOGIN_STATE_COOKIE)
    return response


@router.post("/logout")
async def logout() -> JSONResponse:
    """Clear the `session` cookie."""
    response = JSONResponse({"status": "ok"})
    clear_cookie(response, SESSION_COOKIE_NAME)
    return response
