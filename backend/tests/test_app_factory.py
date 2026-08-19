"""Smoke test for app.main's app factory: importing it configures structured
logging and (no-op, since SENTRY_DSN is unset in this environment) skips
Sentry init without raising, and the app starts up and serves /health.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings


def test_app_imports_and_health_check_responds():
    from app.main import app  # import here so any import-time error surfaces in this test

    assert settings.SENTRY_DSN == ""  # default/unset in this test environment

    with TestClient(app) as client:  # __enter__ runs the lifespan startup hook
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
