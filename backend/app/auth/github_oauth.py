"""GitHub OAuth sign-in for RamanHub.

Mirrors `google_oauth.py`'s shape: a stateless, signed cookie carries the
CSRF `state` across the redirect (no server-side session), and the code
exchange + profile fetch go straight against GitHub's documented endpoints
with `httpx`. Unlike the ORCID *linking* flow this is login, so the state
cookie carries no `user_id`.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt as pyjwt

from app.config import settings

GITHUB_AUTH_ENDPOINT = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_ENDPOINT = "https://github.com/login/oauth/access_token"
GITHUB_USER_ENDPOINT = "https://api.github.com/user"
GITHUB_USER_EMAILS_ENDPOINT = "https://api.github.com/user/emails"
GITHUB_SCOPE = "read:user user:email"

STATE_COOKIE = "gh_oauth_state"
_STATE_TTL_SECONDS = 600


def configured() -> bool:
    return bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
        "scope": GITHUB_SCOPE,
        "state": state,
        "allow_signup": "true",
    }
    return f"{GITHUB_AUTH_ENDPOINT}?{httpx.QueryParams(params)}"


def encode_state_cookie(state: str) -> str:
    now = datetime.now(UTC)
    return pyjwt.encode(
        {
            "state": state,
            "nonce": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def decode_state_cookie(token: str | None) -> dict[str, str] | None:
    if not token:
        return None
    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except pyjwt.PyJWTError:
        return None
    state = payload.get("state")
    return {"state": state} if state else None


async def exchange_code(code: str) -> str:
    """Exchange the authorization code for a GitHub access token."""
    data = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "client_secret": settings.GITHUB_CLIENT_SECRET,
        "code": code,
        "redirect_uri": settings.GITHUB_REDIRECT_URI,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            GITHUB_TOKEN_ENDPOINT, data=data, headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        payload = resp.json()
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not token:
        raise ValueError("GitHub token response did not include an access_token")
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


async def fetch_user(token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(GITHUB_USER_ENDPOINT, headers=_auth_headers(token))
        resp.raise_for_status()
        data = resp.json()
    return {
        "id": data.get("id"),
        "login": data.get("login"),
        "name": data.get("name"),
        "avatar_url": data.get("avatar_url"),
    }


async def fetch_primary_email(token: str) -> str | None:
    """First verified primary email, or None (a GitHub account can hide all
    of its emails)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GITHUB_USER_EMAILS_ENDPOINT, headers=_auth_headers(token)
        )
        resp.raise_for_status()
        entries = resp.json()
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and entry.get("primary") and entry.get("verified"):
            return entry.get("email")
    return None
