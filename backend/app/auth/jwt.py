"""Application session JWT: encode/decode for the `session` cookie.

This is RamanHub's own short-lived app session token — distinct from Google's
ID token, which is only used transiently during `/auth/callback`.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt as pyjwt

from app.config import settings
from app.models.user import User

ALGORITHM = "HS256"


def encode_session_token(user: User) -> str:
    """Issue a signed app session JWT for `user`."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "google_sub": user.google_sub,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRES_HOURS),
    }
    return pyjwt.encode(payload, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_session_token(token: str) -> dict[str, Any] | None:
    """Decode + validate a session JWT. Returns None (never raises) if the
    token is missing, malformed, tampered with, or expired."""
    try:
        return pyjwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except pyjwt.PyJWTError:
        return None
