"""FastAPI auth dependencies.

`get_current_user` / `get_current_user_optional` are a load-bearing contract:
other modules depend on these exact names and signatures to gate endpoints.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.jwt import decode_session_token
from app.db.session import get_db
from app.models.user import User

SESSION_COOKIE_NAME = "session"


def _user_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    payload = decode_session_token(token)
    if payload is None:
        return None

    sub = payload.get("sub")
    if not sub:
        return None

    try:
        user_id = uuid.UUID(str(sub))
    except (ValueError, TypeError, AttributeError):
        return None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None

    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Reads the `session` cookie, decodes+validates the JWT, loads the User
    from DB. Raises HTTPException(401) if missing/invalid/expired token or
    user not found/inactive."""
    user = _user_from_request(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user


def get_current_user_optional(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """Same as `get_current_user` but returns None instead of raising when
    there's no valid session."""
    return _user_from_request(request, db)
