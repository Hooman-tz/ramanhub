"""ORCID OAuth linking, deliberately separate from application sign-in."""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt as pyjwt

from app.config import settings

ORCID_AUTH_ENDPOINT = "https://orcid.org/oauth/authorize"
ORCID_TOKEN_ENDPOINT = "https://orcid.org/oauth/token"
ORCID_STATE_COOKIE = "orcid_link_state"
_STATE_TTL_MINUTES = 10


def configured() -> bool:
    return bool(settings.ORCID_CLIENT_ID and settings.ORCID_CLIENT_SECRET)


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorization_url(state: str) -> str:
    params = {
        "client_id": settings.ORCID_CLIENT_ID,
        "response_type": "code",
        "scope": "/authenticate",
        "redirect_uri": settings.ORCID_REDIRECT_URI,
        "state": state,
    }
    return f"{ORCID_AUTH_ENDPOINT}?{httpx.QueryParams(params)}"


def encode_state_cookie(state: str, user_id: str) -> str:
    now = datetime.now(UTC)
    return pyjwt.encode(
        {
            "state": state,
            "user_id": user_id,
            "iat": now,
            "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
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
    state, user_id = payload.get("state"), payload.get("user_id")
    return {"state": state, "user_id": user_id} if state and user_id else None


async def exchange_code(code: str) -> dict[str, Any]:
    data = {
        "client_id": settings.ORCID_CLIENT_ID,
        "client_secret": settings.ORCID_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.ORCID_REDIRECT_URI,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            ORCID_TOKEN_ENDPOINT,
            data=data,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        payload = response.json()
    return payload if isinstance(payload, dict) else {}