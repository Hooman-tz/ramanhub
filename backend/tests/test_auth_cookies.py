"""Cookie attributes for the split-subdomain production topology.

The web app and the API run on sibling subdomains in production
(`raman.spectra-in.site` / `api.spectra-in.site`). A cookie set without an
explicit `domain` is host-only, so the session the API issues is never sent to
the web origin and sign-in silently fails to stick. Local dev can't catch this
— both halves are `localhost`, and cookies ignore the port — so it's pinned
here instead.
"""
from __future__ import annotations

import pytest
from starlette.responses import JSONResponse

from app.auth import cookies
from app.config import settings


@pytest.fixture()
def restore_settings():
    before = (settings.COOKIE_DOMAIN, settings.ENVIRONMENT)
    yield
    settings.COOKIE_DOMAIN, settings.ENVIRONMENT = before


def _set_cookie_header(response: JSONResponse) -> str:
    return response.headers["set-cookie"]


def test_no_cookie_domain_stays_host_only(restore_settings):
    """Local dev: empty COOKIE_DOMAIN must not emit a Domain attribute."""
    settings.COOKIE_DOMAIN = ""
    settings.ENVIRONMENT = "development"
    response = JSONResponse({})
    cookies.set_session_cookie(response, "session", "tok")
    header = _set_cookie_header(response)
    assert "Domain=" not in header
    assert "HttpOnly" in header
    assert "secure" not in header.lower()


def test_cookie_domain_is_emitted_for_split_subdomains(restore_settings):
    settings.COOKIE_DOMAIN = ".spectra-in.site"
    settings.ENVIRONMENT = "production"
    response = JSONResponse({})
    cookies.set_session_cookie(response, "session", "tok")
    header = _set_cookie_header(response)
    assert "Domain=.spectra-in.site" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "SameSite=lax" in header


def test_state_cookie_shares_the_domain(restore_settings):
    """The OAuth state cookie is written via the web origin's proxy but read
    at the API origin on the provider's redirect — it needs the same parent
    domain as the session cookie or the callback 400s on missing state."""
    settings.COOKIE_DOMAIN = ".spectra-in.site"
    settings.ENVIRONMENT = "production"
    response = JSONResponse({})
    cookies.set_state_cookie(response, "oauth_state", "abc")
    header = _set_cookie_header(response)
    assert "Domain=.spectra-in.site" in header
    assert "Max-Age=600" in header


def test_clear_cookie_matches_the_attributes_used_to_set_it(restore_settings):
    """delete_cookie only removes a cookie when domain/path match the set."""
    settings.COOKIE_DOMAIN = ".spectra-in.site"
    settings.ENVIRONMENT = "production"
    response = JSONResponse({})
    cookies.clear_cookie(response, "session")
    header = _set_cookie_header(response)
    assert "Domain=.spectra-in.site" in header
    assert "Path=/" in header


def test_cookie_domain_whitespace_is_treated_as_unset(restore_settings):
    settings.COOKIE_DOMAIN = "   "
    assert cookies.cookie_domain() is None
