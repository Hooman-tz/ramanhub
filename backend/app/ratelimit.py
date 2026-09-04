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
_post_limiter = RateLimiter(max_calls=20, window_seconds=3600)  # posts/replies / hour
_report_limiter = RateLimiter(max_calls=12, window_seconds=3600)  # abuse reports / hour
# Follows and shares are public, brag-worthy numbers that also feed feed
# visibility, so they are the two actions with the clearest incentive to
# automate. These ceilings are well above real human use and exist to make a
# farming script hit a wall.
_follow_limiter = RateLimiter(max_calls=100, window_seconds=3600)  # 100 follows / hour
_share_limiter = RateLimiter(max_calls=60, window_seconds=3600)  # 60 shares / hour
# Login attempts are pre-auth (there's no user id yet at the point a client
# hits the OAuth callback), so this one is keyed by client IP rather than
# user id — the only identifier available at that point. 10/hour is generous
# for a legitimate user (who at most retries a handful of times) but tight
# enough to blunt scripted brute-forcing of the callback endpoint.
_login_limiter = RateLimiter(max_calls=10, window_seconds=3600)  # 10 login attempts / hour / IP
# LLM-backed endpoints (the "lab consultant" advice endpoint) fan out to a paid
# model per call, so they get their own, tighter ceiling than the social
# actions above — well clear of a human clicking "get advice" a few times while
# iterating on a pipeline, tight enough that a script can't rack up model spend.
_llm_consult_limiter = RateLimiter(max_calls=15, window_seconds=3600)  # 15 LLM consults / hour
# Storing a key makes a live verification call against the named provider, so
# an unthrottled endpoint is a free "is this stolen key valid?" oracle that
# also spends someone else's quota. A real user saves a key once or twice.
_llm_key_write_limiter = RateLimiter(max_calls=10, window_seconds=3600)  # 10 key writes / hour
# Reference-library identification. Matching is index-served and cheap once a
# spectrum's peaks are cached, but a *cold* match pulls arrays out of object
# storage to build that cache, so it still deserves a ceiling.
_library_match_limiter = RateLimiter(max_calls=240, window_seconds=3600)
# Deconvolution is the expensive one: it downloads and interpolates N+1 full
# spectra per call and runs a dense constrained least-squares, so its cost is
# dominated by object-storage round-trips rather than CPU. Unthrottled, it is
# the cheapest way for a script to run up storage egress. Well clear of a human
# trying a handful of component sets on a stubborn sample.
_library_unmix_limiter = RateLimiter(max_calls=30, window_seconds=3600)


def rate_limit_uploads(user: User = Depends(get_current_user)) -> None:
    _upload_limiter.check(str(user.id))


def rate_limit_votes(user: User = Depends(get_current_user)) -> None:
    _vote_limiter.check(str(user.id))


def rate_limit_comments(user: User = Depends(get_current_user)) -> None:
    _comment_limiter.check(str(user.id))


def rate_limit_posts(user: User = Depends(get_current_user)) -> None:
    _post_limiter.check(str(user.id))


def rate_limit_follows(user: User = Depends(get_current_user)) -> None:
    _follow_limiter.check(str(user.id))


def rate_limit_shares(user: User = Depends(get_current_user)) -> None:
    _share_limiter.check(str(user.id))


def rate_limit_reports(user: User = Depends(get_current_user)) -> None:
    _report_limiter.check(str(user.id))


def rate_limit_llm_consult(user: User = Depends(get_current_user)) -> None:
    _llm_consult_limiter.check(str(user.id))


def rate_limit_llm_key_write(user: User = Depends(get_current_user)) -> None:
    _llm_key_write_limiter.check(str(user.id))


def rate_limit_login(request: Request) -> None:
    client_host = request.client.host if request.client else "unknown"
    _login_limiter.check(client_host)


def _caller_key(request: Request, user: User | None) -> str:
    """Identify the caller for endpoints that allow anonymous access.

    The library's read paths use `get_current_user_optional`, so there may be
    no user id to key on. Falling back to client IP mirrors `rate_limit_login`,
    which has the same pre-auth problem.
    """
    if user is not None:
        return f"user:{user.id}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def rate_limit_library_match(
    request: Request, user: User | None = Depends(get_current_user_optional)
) -> None:
    _library_match_limiter.check(_caller_key(request, user))


def rate_limit_library_unmix(
    request: Request, user: User | None = Depends(get_current_user_optional)
) -> None:
    _library_unmix_limiter.check(_caller_key(request, user))
