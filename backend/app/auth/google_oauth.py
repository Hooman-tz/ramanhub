"""Google OAuth2 / OIDC integration for RamanHub.

Implementation note (server-side code flow):

Authlib ships a Starlette-flavored client (`authlib.integrations.starlette_client.OAuth`)
that stores the CSRF `state` and OIDC `nonce` in `request.session`, which requires
Starlette's `SessionMiddleware` to already be registered on the app. `app/main.py` is
owned by a later integration step and does not (yet) configure `SessionMiddleware`, so
rather than taking on that app-wide dependency from within this module, we do the
authorization-code exchange directly against Google's documented, stable OAuth2/OIDC
endpoints with `httpx`, and verify the returned ID token's signature using Authlib's
JOSE primitives (`authlib.jose`) against Google's published JWKS. CSRF `state` and the
OIDC `nonce` are carried in a short-lived, signed, httpOnly cookie (`oauth_state`,
signed with `settings.JWT_SECRET` via PyJWT) instead of a server-side session — this
keeps the whole login round trip stateless on the server, which fits a horizontally
scaled API.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt as pyjwt
from authlib.jose import JsonWebKey
from authlib.jose import jwt as jose_jwt
from authlib.jose.errors import JoseError

from app.config import settings

# Google's OAuth2/OIDC endpoints (stable, published at the OpenID discovery document
# https://accounts.google.com/.well-known/openid-configuration) — hardcoded rather than
# fetched at request time to avoid an extra network round trip (and a flaky dependency)
# on every login.
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
GOOGLE_SCOPE = "openid email profile"

OAUTH_STATE_COOKIE = "oauth_state"
_STATE_TTL_MINUTES = 10


def generate_state_and_nonce() -> tuple[str, str]:
    """Random, unguessable CSRF state + OIDC nonce for one login attempt."""
    return secrets.token_urlsafe(24), secrets.token_urlsafe(24)


def build_authorization_url(state: str, nonce: str) -> str:
    """Build the Google authorization redirect URL for the code flow."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "state": state,
        "nonce": nonce,
        "access_type": "offline",
        "prompt": "select_account",
    }
    query = httpx.QueryParams(params)
    return f"{GOOGLE_AUTH_ENDPOINT}?{query}"


async def exchange_code_for_tokens(code: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens at Google's token endpoint."""
    data = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(GOOGLE_TOKEN_ENDPOINT, data=data)
        resp.raise_for_status()
        return resp.json()


async def _fetch_google_jwks() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GOOGLE_JWKS_URI)
        resp.raise_for_status()
        return resp.json()


async def verify_id_token(id_token: str, nonce: str) -> dict[str, Any]:
    """Verify a Google-issued OIDC ID token's signature + standard claims.

    Returns the decoded claim set on success. Raises ValueError on any failure
    (bad signature, expired, wrong audience/issuer, nonce mismatch) — callers
    should turn that into a 400.
    """
    jwks = await _fetch_google_jwks()
    key_set = JsonWebKey.import_key_set(jwks)
    try:
        claims = jose_jwt.decode(id_token, key_set)
        claims.validate()
    except JoseError as exc:
        raise ValueError(f"invalid Google ID token: {exc}") from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ValueError("unexpected issuer in Google ID token")
    if claims.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise ValueError("unexpected audience in Google ID token")
    if claims.get("nonce") != nonce:
        raise ValueError("nonce mismatch in Google ID token")

    return dict(claims)


def encode_oauth_state_cookie(state: str, nonce: str) -> str:
    """Sign `state`+`nonce` into a short-lived cookie value (CSRF protection
    without server-side session storage)."""
    now = datetime.now(UTC)
    payload = {
        "state": state,
        "nonce": nonce,
        "iat": now,
        "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def decode_oauth_state_cookie(token: str) -> dict[str, str] | None:
    """Decode the `oauth_state` cookie value; None if missing/invalid/expired."""
    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except pyjwt.PyJWTError:
        return None
    state = payload.get("state")
    nonce = payload.get("nonce")
    if not state or not nonce:
        return None
    return {"state": state, "nonce": nonce}
