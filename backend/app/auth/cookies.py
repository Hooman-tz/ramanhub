"""One place that decides how auth cookies are written and cleared.

Why this module exists: the production topology puts the web app and the API
on sibling subdomains (`raman.spectra-in.site` and `api.spectra-in.site`).
Cookies set without an explicit ``domain`` are *host-only*, so a cookie written
by the API is never sent to the web origin — sign-in silently fails to stick.
That never shows up in local dev, where both halves share the host ``localhost``
(cookies ignore the port).

`COOKIE_DOMAIN` fixes that: set it to the registrable parent (leading dot
optional, e.g. ``.spectra-in.site``) in any environment where the two origins
differ, and leave it empty locally to keep cookies host-only.

Clearing matters too. ``delete_cookie`` only reliably removes a cookie when the
``domain``/``path``/``secure``/``samesite`` attributes match the ones used to
set it, so both operations go through here rather than being spelled out at
each call site.
"""
from __future__ import annotations

from starlette.responses import Response

from app.config import settings

# Short-lived OAuth CSRF/state cookies.
STATE_COOKIE_MAX_AGE = 600


def cookie_secure() -> bool:
    """Allow non-Secure cookies only on plain-http local dev."""
    return settings.ENVIRONMENT.lower() not in {"development", "test"}


def cookie_domain() -> str | None:
    """The cookie ``domain``, or None for host-only (the local-dev default)."""
    return settings.COOKIE_DOMAIN.strip() or None


def set_session_cookie(response: Response, name: str, token: str) -> None:
    response.set_cookie(
        name,
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=settings.JWT_EXPIRES_HOURS * 3600,
        domain=cookie_domain(),
        path="/",
    )


def set_state_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=STATE_COOKIE_MAX_AGE,
        domain=cookie_domain(),
        path="/",
    )


def clear_cookie(response: Response, name: str) -> None:
    """Delete a cookie using the same attributes it was set with."""
    response.delete_cookie(
        name,
        domain=cookie_domain(),
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="lax",
    )
