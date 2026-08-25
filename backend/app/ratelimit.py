"""Module 4b: basic rate limiting on uploads and votes/comments, to blunt
spam/abuse (per raman-platform-architecture-v2.md's MODULE 4 requirement).

Deliberately a simple in-process sliding-window limiter, NOT Redis-backed.
Per the doc's Scaling Posture, Redis is explicitly deferred until synchronous
processing becomes a bottleneck — it's not required for the first version.
This limiter is therefore single-instance only: state lives in this
process's memory, resets on restart, and is NOT shared across multiple
backend instances/workers. That's an acceptable, documented limitation at
the current single-instance deployment scale; if/when the backend is
horizontally scaled, this should be swapped for a shared store (Redis or
the DB) rather than papered over.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import Depends, HTTPException, Request, status

from app.auth.deps import get_current_user, get_current_user_optional
from app.models.user import User


class RateLimiter:
    """In-process sliding-window rate limiter. Single-instance only — state
    lives in this process's memory and resets on restart / isn't shared
    across multiple backend instances. Fine at current scale (Scaling
    Posture: Redis is explicitly deferred until there's evidence of need).
    """

    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.monotonic()
        recent = [t for t in self._calls[key] if now - t < self.window_seconds]
        if len(recent) >= self.max_calls:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded"
            )
        recent.append(now)
        self._calls[key] = recent


# Thresholds (per-user, sliding window). Chosen as reasonable defaults for a
# small single-instance deployment — generous enough not to bother normal
# usage, tight enough to blunt naive scripted abuse. Adjust if real usage
# patterns suggest otherwise; there's no other significance to these exact
# numbers.
_upload_limiter = RateLimiter(max_calls=20, window_seconds=3600)  # 20 uploads / hour
_vote_limiter = RateLimiter(max_calls=60, window_seconds=3600)  # 60 vote-toggles / hour
_comment_limiter = RateLimiter(max_calls=30, window_seconds=3600)  # 30 comments / hour
# Login attempts are pre-auth (there's no user id yet at the point a client
# hits the OAuth callback), so this one is keyed by client IP rather than
# user id — the only identifier available at that point. 10/hour is generous
# for a legitimate user (who at most retries a handful of times) but tight
# enough to blunt scripted brute-forcing of the callback endpoint.
_login_limiter = RateLimiter(max_calls=10, window_seconds=3600)  # 10 login attempts / hour / IP
# Pipeline previews are cheap individually (replay a few steps over one
# spectrum, milliseconds) but a user tuning a slider fires many in a row even
# with client-side debouncing, so this ceiling is far higher than the others.
# It exists to stop a script, not to ration normal interactive editing.
_preview_limiter = RateLimiter(max_calls=600, window_seconds=3600)  # 600 previews / hour


def rate_limit_uploads(user: User = Depends(get_current_user)) -> None:
    _upload_limiter.check(str(user.id))


def rate_limit_votes(user: User = Depends(get_current_user)) -> None:
    _vote_limiter.check(str(user.id))


def rate_limit_comments(user: User = Depends(get_current_user)) -> None:
    _comment_limiter.check(str(user.id))


def rate_limit_previews(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
) -> None:
    """Preview is readable by anyone who can read the spectrum, including
    anonymous visitors on a published one, so this falls back to client IP
    when there is no user — unlike the authenticated limiters above, which
    can always key on a user id."""
    key = str(user.id) if user is not None else (request.client.host if request.client else "unknown")
    _preview_limiter.check(key)


def rate_limit_login(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    _login_limiter.check(client_host)
