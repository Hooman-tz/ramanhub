"""`ORCID_ENV` selects the ORCID tenant.

It used to appear in `.env.example` and `render.yaml` while being read by no
Python at all, so `docs/OPERATIONS.md`'s "use the sandbox until production is
approved" instruction could not actually be followed.
"""
from __future__ import annotations

import pytest

from app.auth import orcid_oauth
from app.config import settings


@pytest.fixture()
def restore_orcid_env():
    before = settings.ORCID_ENV
    yield
    settings.ORCID_ENV = before


@pytest.mark.parametrize(
    "value,expected_host",
    [
        ("production", "https://orcid.org"),
        ("sandbox", "https://sandbox.orcid.org"),
        ("SandBox", "https://sandbox.orcid.org"),
        ("  sandbox  ", "https://sandbox.orcid.org"),
    ],
)
def test_selects_tenant(restore_orcid_env, value, expected_host):
    settings.ORCID_ENV = value
    assert orcid_oauth.auth_endpoint().startswith(expected_host)
    assert orcid_oauth.token_endpoint().startswith(expected_host)


@pytest.mark.parametrize("value", ["", "garbage", "prod"])
def test_unknown_values_fail_safe_to_production(restore_orcid_env, value):
    settings.ORCID_ENV = value
    assert orcid_oauth.auth_endpoint().startswith("https://orcid.org")
