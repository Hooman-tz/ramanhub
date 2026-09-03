"""Symmetric encryption for secrets the app must be able to read back.

Used for user-supplied LLM API keys, which — unlike a password — cannot be
hashed, because the backend has to present the original value to the provider
on every call.

The feature is *off* unless `LLM_KEY_ENCRYPTION_KEY` is set. There is
deliberately no plaintext fallback: storing a user's provider key in the clear
because an operator forgot an env var is worse than the feature not existing,
so `byo_llm_enabled()` gates the endpoints and the UI instead.

Fernet gives authenticated encryption (AES-128-CBC + HMAC-SHA256) with a
versioned token format, so a ciphertext tampered with in the database fails
to decrypt rather than decrypting to something attacker-chosen.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretsUnavailable(RuntimeError):
    """No encryption key is configured, or the configured one is malformed."""


def byo_llm_enabled() -> bool:
    """True when secrets can be encrypted, i.e. bring-your-own-key is on."""
    return bool(settings.LLM_KEY_ENCRYPTION_KEY)


@lru_cache(maxsize=1)
def _fernet_for(key: str) -> Fernet:
    """Cached per key value, so tests that monkeypatch the setting get a
    fresh cipher rather than a stale one bound to the old key."""
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise SecretsUnavailable(
            "LLM_KEY_ENCRYPTION_KEY is not a valid Fernet key (expected 44 "
            "urlsafe-base64 characters; generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"`)"
        ) from exc


def _cipher() -> Fernet:
    if not byo_llm_enabled():
        raise SecretsUnavailable("LLM_KEY_ENCRYPTION_KEY is not configured")
    return _fernet_for(settings.LLM_KEY_ENCRYPTION_KEY)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret for storage. The result is safe to put in a text
    column and is not reversible without the configured key."""
    return _cipher().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Reverse `encrypt_secret`. Raises `SecretsUnavailable` when the key is
    missing or the token does not belong to it — which is what happens if the
    encryption key is rotated without re-encrypting stored rows."""
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretsUnavailable(
            "Stored secret could not be decrypted with the configured "
            "LLM_KEY_ENCRYPTION_KEY"
        ) from exc


def last4(secret: str) -> str:
    """The trailing 4 characters, for display. Short secrets are padded so
    this never leaks a whole key by returning it verbatim."""
    return secret[-4:].rjust(4, "•")
