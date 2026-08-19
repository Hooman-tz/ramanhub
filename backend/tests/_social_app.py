"""Shared helper (not a test module itself) for Module 4b's test suite:
builds a TestClient wired with the spectra + votes + comments + trending
routers, mirroring the pattern of `conftest.py`'s `app_client` fixture but
extended with this module's own routers so tests can create a spectrum via
`POST /spectra` and then exercise votes/comments/trending against it.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.routers import comments, spectra, trending, votes


def build_social_client(db_session) -> TestClient:
    test_app = FastAPI()
    test_app.include_router(spectra.router)
    test_app.include_router(votes.router)
    test_app.include_router(comments.router)
    test_app.include_router(trending.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    def _override_get_current_user_optional():
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_user_optional] = _override_get_current_user_optional

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client
