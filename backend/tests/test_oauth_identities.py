"""M3b: `auth_identities` + the GitHub / ORCID sign-in callbacks.

Two tiers, same pattern as tests/test_auth.py:
- `resolve_or_create_user` is exercised directly against a real session.
- the callbacks are driven through a local FastAPI app with `httpx`
  monkeypatched out.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import github_oauth, orcid_oauth
from app.auth.deps import SESSION_COOKIE_NAME
from app.auth.identities import resolve_or_create_user
from app.auth.jwt import decode_session_token, encode_session_token
from app.db.session import get_db
from app.models.auth_identity import AuthIdentity
from app.models.raw_file import RawFile
from app.models.user import User
from app.routers import auth as auth_router
from app.schemas.auth import UserOut

# ---------------------------------------------------------------------------
# resolve_or_create_user
# ---------------------------------------------------------------------------


def test_new_identity_creates_user_and_identity(db_session):
    user = resolve_or_create_user(
        db_session,
        provider="github",
        subject="gh-1",
        email="alice@example.com",
        display_name="Alice",
        avatar_url="https://avatars/alice.png",
    )
    db_session.flush()

    assert user.id is not None
    assert user.google_sub is None
    assert user.email == "alice@example.com"
    assert user.profile_handle  # assigned
    identity = db_session.query(AuthIdentity).filter_by(user_id=user.id).one()
    assert (identity.provider, identity.provider_subject) == ("github", "gh-1")


def test_same_identity_twice_returns_same_user(db_session):
    first = resolve_or_create_user(
        db_session, provider="github", subject="gh-2", email="bob@example.com",
        display_name="Bob",
    )
    db_session.flush()
    second = resolve_or_create_user(
        db_session, provider="github", subject="gh-2", email="bob@example.com",
        display_name="Bob",
    )
    db_session.flush()

    assert first.id == second.id
    assert db_session.query(AuthIdentity).filter_by(provider="github", provider_subject="gh-2").count() == 1


def test_matching_email_attaches_identity_to_existing_user(db_session):
    existing = User(email="carol@example.com", display_name="Carol", google_sub=None)
    db_session.add(existing)
    db_session.flush()

    resolved = resolve_or_create_user(
        db_session, provider="github", subject="gh-3", email="carol@example.com",
        display_name="Carol from GitHub",
    )
    db_session.flush()

    assert resolved.id == existing.id
    identity = db_session.query(AuthIdentity).filter_by(user_id=existing.id).one()
    assert identity.provider == "github"
    assert db_session.query(User).filter_by(email="carol@example.com").count() == 1


def test_guest_is_not_reused_by_email_match(db_session):
    """A guest row never gets adopted by an OAuth login even though it has an
    email — guests use a synthetic `@guest.invalid` address, and the
    email-match branch explicitly skips `is_guest` rows."""
    guest = User(
        email=f"guest-{uuid.uuid4().hex}@guest.invalid",
        google_sub=f"guest:{uuid.uuid4().hex}",
        is_guest=True,
    )
    db_session.add(guest)
    db_session.flush()

    resolved = resolve_or_create_user(
        db_session, provider="github", subject=f"gh-{uuid.uuid4().hex[:8]}",
        email=f"real-{uuid.uuid4().hex[:8]}@example.com", display_name="Real Person",
    )
    db_session.flush()

    assert resolved.id != guest.id
    assert resolved.is_guest is False


def test_orcid_provider_sets_orcid_id(db_session):
    user = resolve_or_create_user(
        db_session, provider="orcid", subject="0000-0002-1825-0097", email=None,
        display_name="Dr Orcid", orcid_id="0000-0002-1825-0097",
    )
    db_session.flush()

    assert user.orcid_id == "0000-0002-1825-0097"
    assert user.email is None
    identity = db_session.query(AuthIdentity).filter_by(user_id=user.id).one()
    assert identity.provider == "orcid"


def test_legacy_google_row_is_adopted_not_duplicated(db_session):
    legacy = User(google_sub="legacy-sub", email="legacy@example.com", display_name="Legacy")
    db_session.add(legacy)
    db_session.flush()

    resolved = resolve_or_create_user(
        db_session, provider="google", subject="legacy-sub", email="legacy@example.com",
        display_name="Legacy",
    )
    db_session.flush()

    assert resolved.id == legacy.id
    assert db_session.query(User).filter_by(google_sub="legacy-sub").count() == 1
    assert db_session.query(AuthIdentity).filter_by(provider="google", provider_subject="legacy-sub").count() == 1


# ---------------------------------------------------------------------------
# GET /auth/github/callback  +  GET /auth/orcid/callback
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_client(db_session):
    app = FastAPI()
    app.include_router(auth_router.router)

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn


def test_github_callback_creates_user_identity_and_session(auth_client, db_session, monkeypatch):
    state = "gh-state-1"
    gh_id = uuid.uuid4().int % 10_000_000
    email = f"octo-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(github_oauth, "exchange_code", _async_return("gh-token"))
    monkeypatch.setattr(
        github_oauth,
        "fetch_user",
        _async_return({"id": gh_id, "login": "octocat", "name": "Octo Cat", "avatar_url": "https://a/o.png"}),
    )
    monkeypatch.setattr(github_oauth, "fetch_primary_email", _async_return(email))

    auth_client.cookies.set(github_oauth.STATE_COOKIE, github_oauth.encode_state_cookie(state))
    resp = auth_client.get(
        "/auth/github/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert SESSION_COOKIE_NAME in resp.cookies
    payload = decode_session_token(resp.cookies[SESSION_COOKIE_NAME])
    user = db_session.get(User, uuid.UUID(payload["sub"]))
    assert user.email == email
    assert user.display_name == "Octo Cat"
    identity = db_session.query(AuthIdentity).filter_by(user_id=user.id).one()
    assert (identity.provider, identity.provider_subject) == ("github", str(gh_id))


def test_github_callback_rejects_bad_state(auth_client, monkeypatch):
    monkeypatch.setattr(github_oauth, "exchange_code", _async_return("gh-token"))
    auth_client.cookies.set(
        github_oauth.STATE_COOKIE, github_oauth.encode_state_cookie("real-state")
    )
    resp = auth_client.get(
        "/auth/github/callback",
        params={"code": "abc", "state": "forged-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_github_callback_migrates_prior_guest_rows(auth_client, db_session, make_raw_file, monkeypatch):
    guest = User(
        email=f"guest-{uuid.uuid4().hex}@guest.invalid",
        google_sub=f"guest:{uuid.uuid4().hex}",
        display_name="Guest",
        is_guest=True,
    )
    db_session.add(guest)
    db_session.commit()
    raw_file = make_raw_file(guest)
    assert db_session.get(RawFile, raw_file.id).owner_id == guest.id

    state = "gh-state-guest"
    gh_id = uuid.uuid4().int % 10_000_000
    monkeypatch.setattr(github_oauth, "exchange_code", _async_return("gh-token"))
    monkeypatch.setattr(
        github_oauth,
        "fetch_user",
        _async_return({"id": gh_id, "login": "newbie", "name": "New Bie", "avatar_url": None}),
    )
    monkeypatch.setattr(
        github_oauth, "fetch_primary_email", _async_return(f"newbie-{uuid.uuid4().hex[:8]}@example.com")
    )

    auth_client.cookies.set(github_oauth.STATE_COOKIE, github_oauth.encode_state_cookie(state))
    auth_client.cookies.set(SESSION_COOKIE_NAME, encode_session_token(guest))
    resp = auth_client.get(
        "/auth/github/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    payload = decode_session_token(resp.cookies[SESSION_COOKIE_NAME])
    new_user_id = uuid.UUID(payload["sub"])
    assert new_user_id != guest.id
    db_session.expire_all()
    assert db_session.get(RawFile, raw_file.id).owner_id == new_user_id
    assert db_session.get(User, guest.id).is_active is False


def test_orcid_callback_creates_user_with_orcid_id(auth_client, db_session, monkeypatch):
    state = "orcid-state-1"
    n = uuid.uuid4().int
    orcid_id = f"0000-{n % 10000:04d}-{(n // 10000) % 10000:04d}-{(n // 100000000) % 10000:04d}"
    monkeypatch.setattr(
        orcid_oauth,
        "exchange_code",
        _async_return({"orcid": orcid_id, "name": "Grace Researcher"}),
    )

    auth_client.cookies.set(
        orcid_oauth.LOGIN_STATE_COOKIE, orcid_oauth.encode_login_state_cookie(state)
    )
    resp = auth_client.get(
        "/auth/orcid/callback",
        params={"code": "xyz", "state": state},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    payload = decode_session_token(resp.cookies[SESSION_COOKIE_NAME])
    user = db_session.get(User, uuid.UUID(payload["sub"]))
    assert user.orcid_id == orcid_id
    assert user.display_name == "Grace Researcher"
    assert db_session.query(AuthIdentity).filter_by(user_id=user.id, provider="orcid").count() == 1

    # An ORCID user has no email — every UserOut response (/users/me,
    # /auth/session, the onboarding write) would 500 on serialisation if the
    # schema still required a value.
    assert user.email is None
    UserOut.model_validate(user)
