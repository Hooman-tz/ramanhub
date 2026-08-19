"""Unit test for app.ratelimit.rate_limit_login — the pre-auth,
per-client-IP rate limiter wired into the /auth/callback endpoint. No DB
required.

Uses a fake client IP reserved for documentation/testing
(TEST-NET-3, RFC 5737) so this test's calls can't collide with the
`_login_limiter` module singleton's state from other test modules that
exercise the real `/auth/callback` endpoint (those go through httpx's
ASGITransport, which reports the client host as `127.0.0.1`).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.ratelimit import rate_limit_login

_FAKE_IP = "203.0.113.5"


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class _FakeRequest:
    def __init__(self, host: str):
        self.client = _FakeClient(host)


def test_rate_limit_login_allows_up_to_limit_then_raises_429():
    request = _FakeRequest(_FAKE_IP)
    for _ in range(10):
        rate_limit_login(request)

    with pytest.raises(HTTPException) as exc_info:
        rate_limit_login(request)
    assert exc_info.value.status_code == 429


def test_rate_limit_login_different_ips_have_independent_limits():
    other_ip_request = _FakeRequest("203.0.113.6")
    for _ in range(10):
        rate_limit_login(other_ip_request)

    unrelated_request = _FakeRequest("203.0.113.7")
    rate_limit_login(unrelated_request)  # should not raise — independent key


def test_rate_limit_login_handles_missing_client():
    class _NoClientRequest:
        client = None

    # Should not raise an AttributeError even with no client info available
    # (falls back to a shared "unknown" key rather than crashing).
    rate_limit_login(_NoClientRequest())
