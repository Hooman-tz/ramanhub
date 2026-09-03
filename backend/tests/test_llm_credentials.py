"""Tests for secret storage and LLM credential resolution.

The security-relevant claims here are: a stored provider key is unreadable
without the configured Fernet key, the feature refuses to operate (rather
than falling back to plaintext) when no encryption key is set, and a user's
own credential wins over the platform's everywhere.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app import llm_credentials
from app.llm_credentials import (
    PROVIDERS,
    llm_available_for,
    platform_credential,
    resolve_for_user,
    user_credential,
)
from app.models.user_llm_credential import UserLLMCredential
from app.security import secrets as secrets_mod


@pytest.fixture()
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(secrets_mod.settings, "LLM_KEY_ENCRYPTION_KEY", key)
    secrets_mod._fernet_for.cache_clear()
    yield key
    secrets_mod._fernet_for.cache_clear()


@pytest.fixture()
def platform_key(monkeypatch):
    monkeypatch.setattr(llm_credentials.settings, "OPENROUTER_API_KEY", "sk-or-platform")
    monkeypatch.setattr(
        llm_credentials.settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )


def _store(db_session, user, *, provider="openai", model=None, key="sk-user-abcd1234"):
    row = UserLLMCredential(
        user_id=user.id,
        provider=provider,
        model=model,
        encrypted_api_key=secrets_mod.encrypt_secret(key),
        key_last4=secrets_mod.last4(key),
    )
    db_session.add(row)
    db_session.commit()
    return row


# --- encryption -----------------------------------------------------------


def test_encrypt_decrypt_round_trip(encryption_key):
    token = secrets_mod.encrypt_secret("sk-or-v1-secret")
    assert token != "sk-or-v1-secret"
    assert "sk-or-v1-secret" not in token
    assert secrets_mod.decrypt_secret(token) == "sk-or-v1-secret"


def test_encryption_is_not_deterministic(encryption_key):
    """Fernet tokens carry a random IV, so two encryptions of the same key do
    not look alike — a reader of the table cannot tell which users share a
    key."""
    assert secrets_mod.encrypt_secret("same") != secrets_mod.encrypt_secret("same")


def test_secrets_refuse_to_operate_without_a_key(monkeypatch):
    """No plaintext fallback: with no encryption key configured, storing a
    secret raises rather than silently writing it in the clear."""
    monkeypatch.setattr(secrets_mod.settings, "LLM_KEY_ENCRYPTION_KEY", "")
    secrets_mod._fernet_for.cache_clear()
    assert secrets_mod.byo_llm_enabled() is False
    with pytest.raises(secrets_mod.SecretsUnavailable):
        secrets_mod.encrypt_secret("sk-nope")


def test_token_from_another_key_does_not_decrypt(encryption_key, monkeypatch):
    token = secrets_mod.encrypt_secret("sk-original")
    monkeypatch.setattr(
        secrets_mod.settings, "LLM_KEY_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    secrets_mod._fernet_for.cache_clear()
    with pytest.raises(secrets_mod.SecretsUnavailable):
        secrets_mod.decrypt_secret(token)


def test_last4_never_returns_a_whole_short_secret():
    assert secrets_mod.last4("sk-or-v1-abcd1234") == "1234"
    assert secrets_mod.last4("ab") == "••ab"


# --- resolution -----------------------------------------------------------


def test_platform_credential_is_none_without_a_key(monkeypatch):
    monkeypatch.setattr(llm_credentials.settings, "OPENROUTER_API_KEY", "")
    assert platform_credential() is None


def test_platform_credential_leaves_model_to_the_call_site(platform_key):
    cred = platform_credential()
    assert cred is not None
    assert cred.is_user_supplied is False
    assert cred.is_openrouter is True
    # None => app.llm applies the per-call-site override, then OPENROUTER_MODEL.
    assert cred.model is None


def test_user_credential_wins_over_the_platform(db_session, make_user, encryption_key, platform_key):
    user = make_user()
    _store(db_session, user, provider="openai", key="sk-user-abcd1234")

    cred = resolve_for_user(db_session, user.id)
    assert cred is not None
    assert cred.is_user_supplied is True
    assert cred.provider == "openai"
    assert cred.api_key == "sk-user-abcd1234"
    assert cred.base_url == PROVIDERS["openai"].base_url
    assert cred.is_openrouter is False


def test_user_without_a_credential_falls_back_to_the_platform(
    db_session, make_user, encryption_key, platform_key
):
    user = make_user()
    cred = resolve_for_user(db_session, user.id)
    assert cred is not None
    assert cred.is_user_supplied is False


def test_null_model_resolves_to_the_provider_default(
    db_session, make_user, encryption_key, platform_key
):
    user = make_user()
    _store(db_session, user, provider="groq", model=None)
    cred = resolve_for_user(db_session, user.id)
    assert cred is not None
    assert cred.model == PROVIDERS["groq"].default_model


def test_stored_model_is_used_verbatim(db_session, make_user, encryption_key, platform_key):
    user = make_user()
    _store(db_session, user, provider="openai", model="gpt-4o")
    cred = resolve_for_user(db_session, user.id)
    assert cred is not None
    assert cred.model == "gpt-4o"


def test_user_credential_ignored_when_the_feature_is_off(
    db_session, make_user, encryption_key, platform_key, monkeypatch
):
    """An operator who unsets the encryption key turns the feature off; stored
    rows become unreadable and users fall back to the platform route rather
    than losing LLM features entirely."""
    user = make_user()
    _store(db_session, user, provider="openai")
    monkeypatch.setattr(secrets_mod.settings, "LLM_KEY_ENCRYPTION_KEY", "")
    secrets_mod._fernet_for.cache_clear()

    assert user_credential(db_session, user.id) is None
    cred = resolve_for_user(db_session, user.id)
    assert cred is not None and cred.is_user_supplied is False


def test_unknown_stored_provider_falls_back(
    db_session, make_user, encryption_key, platform_key
):
    """A provider dropped from the allowlist after a row was written must not
    500 anyone's upload."""
    user = make_user()
    _store(db_session, user, provider="retired-provider")
    assert user_credential(db_session, user.id) is None
    assert resolve_for_user(db_session, user.id).is_user_supplied is False


def test_undecryptable_row_falls_back(db_session, make_user, encryption_key, platform_key):
    """Encryption key rotated without re-encrypting stored rows."""
    user = make_user()
    row = _store(db_session, user)
    row.encrypted_api_key = Fernet(Fernet.generate_key()).encrypt(b"sk-other").decode()
    db_session.add(row)
    db_session.commit()

    assert user_credential(db_session, user.id) is None
    assert resolve_for_user(db_session, user.id).is_user_supplied is False


def test_llm_available_for_is_true_on_own_key_with_no_platform_key(
    db_session, make_user, encryption_key, monkeypatch
):
    """The whole point of BYO: a deployment with no OpenRouter key at all
    still gives LLM features to users who brought their own."""
    monkeypatch.setattr(llm_credentials.settings, "OPENROUTER_API_KEY", "")
    user = make_user()
    other = make_user()
    _store(db_session, user, provider="openai")

    assert llm_available_for(db_session, user.id) is True
    assert llm_available_for(db_session, other.id) is False


def test_repr_does_not_leak_the_key(db_session, make_user, encryption_key, platform_key):
    user = make_user()
    _store(db_session, user, provider="openai", key="sk-user-supersecret")
    cred = resolve_for_user(db_session, user.id)
    assert "supersecret" not in repr(cred)
    assert "redacted" in repr(cred)
