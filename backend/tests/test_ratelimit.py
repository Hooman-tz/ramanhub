"""Unit tests for the in-process sliding-window rate limiter
(`app.ratelimit.RateLimiter`). No DB required."""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from app.ratelimit import RateLimiter


def test_allows_up_to_max_calls_then_raises_429():
    limiter = RateLimiter(max_calls=3, window_seconds=60)
    for _ in range(3):
        limiter.check("user-a")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("user-a")
    assert exc_info.value.status_code == 429


def test_different_keys_have_independent_limits():
    limiter = RateLimiter(max_calls=2, window_seconds=60)
    limiter.check("user-a")
    limiter.check("user-a")
    # user-a is now at the limit, but user-b should be unaffected.
    limiter.check("user-b")
    limiter.check("user-b")

    with pytest.raises(HTTPException):
        limiter.check("user-a")
    with pytest.raises(HTTPException):
        limiter.check("user-b")


def test_calls_outside_window_are_forgotten():
    limiter = RateLimiter(max_calls=1, window_seconds=0.05)
    limiter.check("user-a")

    with pytest.raises(HTTPException):
        limiter.check("user-a")

    time.sleep(0.08)
    # Old call has aged out of the window, so this should succeed again.
    limiter.check("user-a")
