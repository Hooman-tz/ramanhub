"""Tests for Module 0: app.auth (google_oauth/jwt/deps) and the
auth/users/licenses routers.

Two tiers, mirroring the pragmatic pattern in tests/test_models_smoke.py:

- DB-independent: `app.auth.deps` (get_current_user / get_current_user_optional)
  and the `UserUpdate` orcid_id validator are pure functions/pydantic models —
  tested directly against fakes, no database required, always run.
- DB-dependent: the actual HTTP routers (`/auth/callback`, `/users/me`) touch
  real SQLAlchemy sessions against the `users`/`licenses` tables, which use
  Postgres-native types (UUID, gen_random_uuid()) that don't work against
  sqlite. These run only when DATABASE_URL points at a reachable Postgres,
  and are skipped otherwise.

The test app is a *local*, self-contained `FastAPI()` instance that mounts
only this module's routers — `app.main.app` is still frozen/unwired at this
point, so tests don't depend on the integration step having happened.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import jwt as pyjwt
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.auth import google_oauth
from app.auth.deps import get_current_user, get_current_user_optional
from app.auth.jwt import decode_session_token, encode_session_token
from app.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.models.auth_identity import AuthIdentity
from app.models.license import License
from app.models.user import User
from app.routers import auth as auth_router
from app.routers import licenses as licenses_router
from app.routers import users as users_router
from app.schemas.auth import UserUpdate
from app.seed.seed_data import seed_licenses
from tests._db_url import get_test_database_url

# ---------------------------------------------------------------------------
# DB availability — uses a dedicated `<dbname>_test` database, never the dev
# DATABASE_URL, so running the suite can't wipe local dev data (see
# tests/_db_url.py).
# ---------------------------------------------------------------------------

DB_URL = get_test_database_url()
requires_db = pytest.mark.skipif(DB_URL is None, reason="No reachable DATABASE_URL")


def run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fakes for DB-independent deps tests
# ---------------------------------------------------------------------------


class DummyRequest:
    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.cookies = cookies or {}
        self.headers = headers or {}


class FakeUser:
    def __init__(self, id_, is_active=True):
        self.id = id_
        self.is_active = is_active
        self.google_sub = "fake-google-sub"


class FakeDB:
    """Minimal stand-in exposing only the `.get(Model, pk)` method that
    `app.auth.deps._user_from_request` needs."""

    def __init__(self, users: dict):
        self._users = users

    def get(self, model, pk):
        assert model is User
        return self._users.get(pk)


def _make_token(sub: str, secret: str | None = None, expired: bool = False) -> str:
    secret = secret or settings.JWT_SECRET
    now = datetime.now(UTC)
    exp = now - timedelta(hours=1) if expired else now + timedelta(hours=1)
    return pyjwt.encode({"sub": sub, "exp": exp}, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# jwt.py
# ---------------------------------------------------------------------------


class _UserLike:
    def __init__(self):
        self.id = uuid.uuid4()
        self.google_sub = "sub-123"


def test_encode_decode_session_token_round_trip():
    user = _UserLike()
    token = encode_session_token(user)
    payload = decode_session_token(token)
    assert payload is not None
    assert payload["sub"] == str(user.id)
    # The session token carries only `sub` since M3b — provider identity
    # lives in `auth_identities`, and a user can have several.
    assert "google_sub" not in payload


def test_decode_session_token_rejects_garbage():
    assert decode_session_token("not-a-jwt") is None


def test_decode_session_token_rejects_expired():
    token = _make_token(str(uuid.uuid4()), expired=True)
    assert decode_session_token(token) is None


def test_decode_session_token_rejects_wrong_secret():
    token = _make_token(str(uuid.uuid4()), secret="some-other-secret")
    assert decode_session_token(token) is None


# ---------------------------------------------------------------------------
# deps.py — get_current_user / get_current_user_optional
# ---------------------------------------------------------------------------


def test_get_current_user_valid_token_returns_user():
    user_id = uuid.uuid4()
    user = FakeUser(user_id)
    db = FakeDB({user_id: user})
    token = _make_token(str(user_id))
    request = DummyRequest({"session": token})

    result = get_current_user(request, db)
    assert result is user


def test_get_current_user_missing_cookie_raises_401():
    from fastapi import HTTPException

    db = FakeDB({})
    request = DummyRequest({})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request, db)
    assert exc_info.value.status_code == 401


def test_get_current_user_expired_token_raises_401():
    from fastapi import HTTPException

    db = FakeDB({})
    request = DummyRequest({"session": _make_token(str(uuid.uuid4()), expired=True)})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request, db)
    assert exc_info.value.status_code == 401


def test_get_current_user_tampered_token_raises_401():
    from fastapi import HTTPException

    db = FakeDB({})
    request = DummyRequest({"session": _make_token(str(uuid.uuid4())) + "tamper"})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request, db)
    assert exc_info.value.status_code == 401


def test_get_current_user_inactive_user_raises_401():
    from fastapi import HTTPException

    user_id = uuid.uuid4()
    user = FakeUser(user_id, is_active=False)
    db = FakeDB({user_id: user})
    request = DummyRequest({"session": _make_token(str(user_id))})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request, db)
    assert exc_info.value.status_code == 401


def test_get_current_user_deleted_user_raises_401():
    from fastapi import HTTPException

    db = FakeDB({})  # user id not present -> "deleted"
    request = DummyRequest({"session": _make_token(str(uuid.uuid4()))})
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(request, db)
    assert exc_info.value.status_code == 401


def test_get_current_user_optional_valid_token_returns_user():
    user_id = uuid.uuid4()
    user = FakeUser(user_id)
    db = FakeDB({user_id: user})
    request = DummyRequest({"session": _make_token(str(user_id))})
    assert get_current_user_optional(request, db) is user


def test_get_current_user_optional_missing_cookie_returns_none():
    db = FakeDB({})
    request = DummyRequest({})
    assert get_current_user_optional(request, db) is None


def test_get_current_user_optional_expired_returns_none():
    db = FakeDB({})
    request = DummyRequest({"session": _make_token(str(uuid.uuid4()), expired=True)})
    assert get_current_user_optional(request, db) is None


def test_get_current_user_optional_inactive_user_returns_none():
    user_id = uuid.uuid4()
    user = FakeUser(user_id, is_active=False)
    db = FakeDB({user_id: user})
    request = DummyRequest({"session": _make_token(str(user_id))})
    assert get_current_user_optional(request, db) is None


# ---------------------------------------------------------------------------
# schemas/auth.py — orcid_id validation (no DB / HTTP needed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "orcid_id",
    ["0000-0002-1825-0097", "0000-0001-5109-3700", "0000-0002-1694-233X"],
)
def test_orcid_id_valid_format_accepted(orcid_id):
    payload = UserUpdate(orcid_id=orcid_id)
    assert payload.orcid_id == orcid_id


@pytest.mark.parametrize(
    "orcid_id",
    ["not-an-orcid", "0000-0002-1825", "0000-0002-1825-00979", "0000000218250097"],
)
def test_orcid_id_invalid_format_rejected(orcid_id):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        UserUpdate(orcid_id=orcid_id)


# ---------------------------------------------------------------------------
# DB-backed fixtures + router integration tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(DB_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(eng)
    yield eng
    # Deliberately NOT dropping tables here (used to call
    # `Base.metadata.drop_all(eng)`): this fixture points at the same
    # physical Postgres test database as `conftest.py`'s session-scoped
    # `engine` fixture (both resolve `DB_URL`/`get_test_database_url()` to
    # the same `<dbname>_test` DB). Dropping tables at this module's
    # teardown was wiping them out from under every DB-backed test file that
    # happens to run later in the same pytest session (whichever file's
    # collection order puts it after this one), causing spurious
    # `UndefinedTable` failures unrelated to those files' own code.
    # `create_all` above is idempotent, so leaving tables in place here is
    # harmless; `conftest.py`'s session fixture still drops everything once,
    # at the very end of the whole suite.


@pytest.fixture()
def db_session(engine):
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.query(User).delete()
        # Licenses are NOT this module's to destroy. `conftest._seed_registry`
        # commits the canonical rows once per session, and every DB-backed
        # test file relies on them still being there — publishing a spectrum
        # 422s with "Choose a valid publication license." without them.
        # Emptying the table here left it empty for whichever files pytest
        # happens to collect after this one (test_comments, test_search,
        # test_votes, test_trending, test_spectrum_data, test_public_
        # community — 38 failures), while every one of those files passed
        # when run on its own. Delete for this module's own isolation, then
        # put the shared seed back.
        session.query(License).delete()
        seed_licenses(session)
        session.commit()
        session.close()


@pytest.fixture()
def test_app(db_session):
    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(users_router.router)
    app.include_router(licenses_router.router)

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    return app


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


FAKE_GOOGLE_TOKENS = {"id_token": "fake-id-token", "access_token": "fake-access-token"}


def _fake_claims(sub: str, email: str, name: str, picture: str) -> dict:
    return {
        "iss": "https://accounts.google.com",
        "aud": settings.GOOGLE_CLIENT_ID,
        "sub": sub,
        "email": email,
        "name": name,
        "picture": picture,
    }


@requires_db
def test_login_redirects_to_google_and_sets_state_cookie(test_app):
    async def _run():
        async with _client(test_app) as client:
            resp = await client.get("/auth/login", follow_redirects=False)
            assert resp.status_code == 302
            assert resp.headers["location"].startswith(google_oauth.GOOGLE_AUTH_ENDPOINT)
            assert google_oauth.OAUTH_STATE_COOKIE in resp.cookies

    run_async(_run())


@requires_db
def test_callback_creates_new_user_and_sets_session_cookie(test_app, db_session):
    state, nonce = "state-abc", "nonce-abc"
    cookie_value = google_oauth.encode_oauth_state_cookie(state, nonce)
    claims = _fake_claims("google-sub-new", "new@example.com", "New User", "https://img/pic.png")

    async def _run():
        with (
            patch.object(
                google_oauth, "exchange_code_for_tokens", return_value=FAKE_GOOGLE_TOKENS
            ) as mock_exchange,
            patch.object(google_oauth, "verify_id_token", return_value=claims) as mock_verify,
        ):
            async with _client(test_app) as client:
                client.cookies.set(google_oauth.OAUTH_STATE_COOKIE, cookie_value)
                resp = await client.get(
                    "/auth/callback",
                    params={"code": "auth-code-123", "state": state},
                    follow_redirects=False,
                )
        assert resp.status_code == 302
        assert resp.headers["location"] == settings.FRONTEND_URL
        assert "session" in resp.cookies
        mock_exchange.assert_awaited_once_with("auth-code-123")
        mock_verify.assert_awaited_once()

        session_token = resp.cookies["session"]
        payload = decode_session_token(session_token)
        assert payload is not None

    run_async(_run())

    # New OAuth sign-ups leave `google_sub` NULL and get an `AuthIdentity`
    # row instead — look the user up by email.
    user = db_session.query(User).filter(User.email == "new@example.com").one()
    assert user.google_sub is None
    assert user.display_name == "New User"
    assert user.avatar_url == "https://img/pic.png"
    identity = db_session.query(AuthIdentity).filter(AuthIdentity.user_id == user.id).one()
    assert (identity.provider, identity.provider_subject) == ("google", "google-sub-new")


@requires_db
def test_callback_upserts_existing_user_by_google_sub(test_app, db_session):
    existing = User(
        google_sub="google-sub-existing",
        email="old@example.com",
        display_name="Old Name",
    )
    db_session.add(existing)
    db_session.commit()
    existing_id = existing.id

    state, nonce = "state-xyz", "nonce-xyz"
    cookie_value = google_oauth.encode_oauth_state_cookie(state, nonce)
    claims = _fake_claims(
        "google-sub-existing", "updated@example.com", "Updated Name", "https://img/new.png"
    )

    async def _run():
        with (
            patch.object(google_oauth, "exchange_code_for_tokens", return_value=FAKE_GOOGLE_TOKENS),
            patch.object(google_oauth, "verify_id_token", return_value=claims),
        ):
            async with _client(test_app) as client:
                client.cookies.set(google_oauth.OAUTH_STATE_COOKIE, cookie_value)
                resp = await client.get(
                    "/auth/callback",
                    params={"code": "auth-code-456", "state": state},
                    follow_redirects=False,
                )
        assert resp.status_code == 302

    run_async(_run())

    db_session.expire_all()
    rows = db_session.query(User).filter(User.google_sub == "google-sub-existing").all()
    assert len(rows) == 1
    updated = rows[0]
    assert updated.id == existing_id
    assert updated.email == "updated@example.com"
    assert updated.display_name == "Updated Name"
    assert updated.avatar_url == "https://img/new.png"


@requires_db
def test_callback_state_mismatch_returns_400(test_app):
    cookie_value = google_oauth.encode_oauth_state_cookie("state-real", "nonce-real")

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set(google_oauth.OAUTH_STATE_COOKIE, cookie_value)
            resp = await client.get(
                "/auth/callback",
                params={"code": "some-code", "state": "state-wrong"},
                follow_redirects=False,
            )
        assert resp.status_code == 400

    run_async(_run())


@requires_db
def test_callback_missing_code_returns_400(test_app):
    async def _run():
        async with _client(test_app) as client:
            resp = await client.get("/auth/callback", params={"state": "whatever"})
        assert resp.status_code == 400

    run_async(_run())


@requires_db
@requires_db
def test_dev_login_is_404_outside_development(test_app, db_session, monkeypatch):
    async def _run():
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        async with _client(test_app) as client:
            resp = await client.get("/auth/dev-login", follow_redirects=False)
            assert resp.status_code == 404

    run_async(_run())


@requires_db
def test_dev_login_issues_a_full_account_session_in_development(test_app, db_session, monkeypatch):
    async def _run():
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        async with _client(test_app) as client:
            resp = await client.get(
                "/auth/dev-login",
                params={"email": "devtester@example.com"},
                follow_redirects=False,
            )
            assert resp.status_code == 302
            assert "session=" in "".join(resp.headers.get_list("set-cookie"))
        user = (
            db_session.query(User)
            .filter(User.email == "devtester@example.com")
            .one()
        )
        assert user.is_guest is False

    run_async(_run())


@requires_db
def test_logout_clears_session_cookie(test_app):
    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", "some-token")
            resp = await client.post("/auth/logout")
            assert resp.status_code == 200
            set_cookie_headers = resp.headers.get_list("set-cookie")
            assert any("session=" in h and ("Max-Age=0" in h or "expires=" in h.lower()) for h in set_cookie_headers)

    run_async(_run())


@requires_db
def test_get_users_me_requires_auth(test_app):
    async def _run():
        async with _client(test_app) as client:
            resp = await client.get("/users/me")
        assert resp.status_code == 401

    run_async(_run())


@requires_db
def test_get_users_me_returns_current_user(test_app, db_session):
    user = User(google_sub="sub-me", email="me@example.com", display_name="Me")
    db_session.add(user)
    db_session.commit()
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            resp = await client.get("/users/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "me@example.com"
        assert body["display_name"] == "Me"
        assert body["id"] == str(user.id)

    run_async(_run())


@requires_db
def test_patch_users_me_valid_orcid_accepted(test_app, db_session):
    user = User(google_sub="sub-orcid-ok", email="orcid-ok@example.com")
    db_session.add(user)
    db_session.commit()
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            resp = await client.patch(
                "/users/me", json={"orcid_id": "0000-0002-1825-0097", "display_name": "Dr. Test"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["orcid_id"] == "0000-0002-1825-0097"
        assert body["display_name"] == "Dr. Test"

    run_async(_run())


@requires_db
def test_patch_users_me_invalid_orcid_rejected_422(test_app, db_session):
    user = User(google_sub="sub-orcid-bad", email="orcid-bad@example.com")
    db_session.add(user)
    db_session.commit()
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            resp = await client.patch("/users/me", json={"orcid_id": "not-valid"})
        assert resp.status_code == 422

    run_async(_run())


@requires_db
def test_get_licenses_is_public_and_lists_seeded_licenses(test_app, db_session):
    # merge(), not add_all(): these ids are the same ones the session-scoped
    # seed already commits, so a plain insert is a primary-key collision the
    # moment the table is not empty. It only worked before because the
    # teardown above used to leave the table empty for everyone.
    for row in (
        License(id="CC-BY-4.0", name="Creative Commons Attribution 4.0", url="https://x", is_default=True),
        License(id="CC0-1.0", name="CC0 1.0", url="https://y", is_default=False),
    ):
        db_session.merge(row)
    db_session.commit()

    async def _run():
        async with _client(test_app) as client:
            resp = await client.get("/licenses")
        assert resp.status_code == 200
        body = resp.json()
        ids = {row["id"] for row in body}
        assert {"CC-BY-4.0", "CC0-1.0"} <= ids

    run_async(_run())
