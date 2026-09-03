"""Tests for `/v1/users/me/llm-key` — the bring-your-own-key endpoints.

The load-bearing claims: the stored key never comes back out, an unknown
provider is rejected (so the server never fetches a user-chosen URL), a key
is verified with the provider before it is stored, and closing an account
forgets the key even though account deletion only anonymizes the user row.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_full_user, get_current_user
from app.db.session import get_db
from app.llm import LLMError
from app.models.user_llm_credential import UserLLMCredential
from app.routers import llm_settings
from app.security import secrets as secrets_mod

GOOD_KEY = "sk-or-v1-abcdefgh1234"


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    monkeypatch.setattr(
        secrets_mod.settings, "LLM_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    secrets_mod._fernet_for.cache_clear()
    yield
    secrets_mod._fernet_for.cache_clear()


@pytest.fixture()
def key_client(db_session):
    test_app = FastAPI()
    test_app.include_router(llm_settings.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_full_user] = _override_user
    test_app.dependency_overrides[get_current_user] = _override_user

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


@pytest.fixture()
def verifies_ok(monkeypatch):
    """Stand in for the live verification call the PUT makes."""
    calls = []

    async def _fake(**kwargs):
        calls.append(kwargs)
        return {"ok": True}

    monkeypatch.setattr(llm_settings, "complete_json", _fake)
    return calls


def test_status_reports_not_configured_and_lists_providers(key_client, make_user):
    key_client.set_current_user(make_user())
    body = key_client.get("/v1/users/me/llm-key").json()

    assert body["enabled"] is True
    assert body["configured"] is False
    assert body["key_last4"] is None
    slugs = {p["slug"] for p in body["providers"]}
    assert "openrouter" in slugs and "openai" in slugs


def test_put_stores_the_key_and_returns_only_the_last_four(
    key_client, make_user, db_session, verifies_ok
):
    key_client.set_current_user(make_user())
    resp = key_client.put(
        "/v1/users/me/llm-key",
        json={"provider": "openrouter", "api_key": GOOD_KEY, "model": "z-ai/glm-5.2:free"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["provider"] == "openrouter"
    assert body["model"] == "z-ai/glm-5.2:free"
    assert body["key_last4"] == "1234"
    # The key itself must not appear anywhere in the response.
    assert GOOD_KEY not in resp.text


def test_stored_key_is_encrypted_at_rest(key_client, make_user, db_session, verifies_ok):
    user = make_user()
    key_client.set_current_user(user)
    key_client.put(
        "/v1/users/me/llm-key", json={"provider": "openai", "api_key": GOOD_KEY}
    )

    row = db_session.get(UserLLMCredential, user.id)
    assert row is not None
    assert GOOD_KEY not in row.encrypted_api_key
    assert secrets_mod.decrypt_secret(row.encrypted_api_key) == GOOD_KEY


def test_put_verifies_against_the_chosen_provider_before_storing(
    key_client, make_user, verifies_ok
):
    key_client.set_current_user(make_user())
    key_client.put("/v1/users/me/llm-key", json={"provider": "groq", "api_key": GOOD_KEY})

    assert len(verifies_ok) == 1
    credential = verifies_ok[0]["credential"]
    assert credential.api_key == GOOD_KEY
    assert credential.provider == "groq"
    assert credential.is_user_supplied is True


def test_a_key_the_provider_rejects_is_not_stored(
    key_client, make_user, db_session, monkeypatch
):
    async def _fails(**kwargs):
        raise LLMError("401 Unauthorized: invalid api key")

    monkeypatch.setattr(llm_settings, "complete_json", _fails)
    user = make_user()
    key_client.set_current_user(user)

    resp = key_client.put(
        "/v1/users/me/llm-key", json={"provider": "openai", "api_key": GOOD_KEY}
    )
    assert resp.status_code == 400
    assert "did not work" in resp.json()["detail"]
    assert db_session.get(UserLLMCredential, user.id) is None


def test_unknown_provider_is_rejected(key_client, make_user, verifies_ok):
    """The provider allowlist is what keeps the server from being pointed at a
    user-chosen URL."""
    key_client.set_current_user(make_user())
    resp = key_client.put(
        "/v1/users/me/llm-key",
        json={"provider": "http://169.254.169.254/", "api_key": GOOD_KEY},
    )
    assert resp.status_code == 400
    assert verifies_ok == []


def test_key_with_illegal_characters_is_rejected(key_client, make_user, verifies_ok):
    key_client.set_current_user(make_user())
    resp = key_client.put(
        "/v1/users/me/llm-key",
        json={"provider": "openai", "api_key": "sk-bad\nX-Injected: header"},
    )
    assert resp.status_code == 422
    assert verifies_ok == []


def test_put_replaces_an_existing_key(key_client, make_user, db_session, verifies_ok):
    user = make_user()
    key_client.set_current_user(user)
    key_client.put(
        "/v1/users/me/llm-key", json={"provider": "openai", "api_key": GOOD_KEY}
    )
    key_client.put(
        "/v1/users/me/llm-key",
        json={"provider": "groq", "api_key": "gsk-replacement-9999"},
    )

    rows = db_session.query(UserLLMCredential).filter_by(user_id=user.id).all()
    assert len(rows) == 1
    assert rows[0].provider == "groq"
    assert rows[0].key_last4 == "9999"


def test_delete_removes_the_key_and_is_idempotent(
    key_client, make_user, db_session, verifies_ok
):
    user = make_user()
    key_client.set_current_user(user)
    key_client.put(
        "/v1/users/me/llm-key", json={"provider": "openai", "api_key": GOOD_KEY}
    )

    assert key_client.delete("/v1/users/me/llm-key").status_code == 204
    assert db_session.get(UserLLMCredential, user.id) is None
    assert key_client.delete("/v1/users/me/llm-key").status_code == 204


def test_endpoints_503_when_the_feature_is_disabled(
    key_client, make_user, monkeypatch, verifies_ok
):
    monkeypatch.setattr(secrets_mod.settings, "LLM_KEY_ENCRYPTION_KEY", "")
    secrets_mod._fernet_for.cache_clear()
    key_client.set_current_user(make_user())

    # GET still answers, so the client can read `enabled` and hide the card.
    status_body = key_client.get("/v1/users/me/llm-key").json()
    assert status_body["enabled"] is False

    resp = key_client.put(
        "/v1/users/me/llm-key", json={"provider": "openai", "api_key": GOOD_KEY}
    )
    assert resp.status_code == 503
    assert verifies_ok == []


def test_anonymous_caller_is_rejected(key_client):
    key_client.set_current_user(None)
    assert key_client.get("/v1/users/me/llm-key").status_code == 401


def test_closing_an_account_forgets_the_stored_key(
    key_client, make_user, db_session, verifies_ok
):
    """`DELETE /users/me` anonymizes rather than deletes the users row, so the
    FK cascade never fires — the key must be dropped explicitly."""
    from fastapi import FastAPI as _FastAPI
    from fastapi.testclient import TestClient as _TestClient

    import app.routers.users as users_router

    user = make_user()
    key_client.set_current_user(user)
    key_client.put(
        "/v1/users/me/llm-key", json={"provider": "openai", "api_key": GOOD_KEY}
    )
    assert db_session.get(UserLLMCredential, user.id) is not None

    def _override_get_db():
        yield db_session

    users_app = _FastAPI()
    users_app.include_router(users_router.router)
    users_app.dependency_overrides[get_db] = _override_get_db
    users_app.dependency_overrides[get_current_full_user] = lambda: user
    assert _TestClient(users_app).delete("/users/me").status_code == 204

    assert db_session.get(UserLLMCredential, user.id) is None
