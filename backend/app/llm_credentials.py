"""Which key, endpoint, and model does this LLM call use?

Two answers are possible:

* the **platform credential** — our OpenRouter key, routed through the
  free-model router (`OPENROUTER_MODEL`), which is what every user gets by
  default; or
* a **user credential** — a key the user stored in Settings, pointing at a
  provider of their choosing. Their spectra headers, abstracts, and questions
  then never transit our account, and they spend their own quota rather than
  the shared free tier's 50-requests-per-day ceiling.

`resolve_for_user` is the single entry point. Every LLM call site passes the
result to `complete_json`, so the choice is made in one place rather than
five.

**Providers are a fixed allowlist with fixed base URLs.** A user-supplied
base URL would mean the server issuing outbound requests to an address the
user picked — the classic SSRF shape, with the cloud metadata endpoint one
typo away — so the API validates `provider` against `PROVIDERS` and the URL
is never taken from the request. Every entry below speaks the OpenAI
chat-completions dialect, which is what `app.llm` is built on.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import settings
from app.models.user_llm_credential import UserLLMCredential
from app.security.secrets import SecretsUnavailable, byo_llm_enabled, decrypt_secret

logger = logging.getLogger(__name__)

OPENROUTER = "openrouter"


@dataclass(frozen=True)
class ProviderSpec:
    slug: str
    label: str
    base_url: str
    default_model: str
    # Shown in the settings UI next to the key field, so a user knows where to
    # get one and roughly what a valid model slug looks like.
    key_hint: str


PROVIDERS: dict[str, ProviderSpec] = {
    OPENROUTER: ProviderSpec(
        slug=OPENROUTER,
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="openrouter/free",
        key_hint="Starts with sk-or-. Models look like anthropic/claude-sonnet-5.",
    ),
    "openai": ProviderSpec(
        slug="openai",
        label="OpenAI",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        key_hint="Starts with sk-. Models look like gpt-4o-mini.",
    ),
    "anthropic": ProviderSpec(
        slug="anthropic",
        label="Anthropic",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-haiku-4-5-20251001",
        key_hint="Starts with sk-ant-. Uses Anthropic's OpenAI-compatible endpoint.",
    ),
    "groq": ProviderSpec(
        slug="groq",
        label="Groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        key_hint="Starts with gsk_. Models look like llama-3.3-70b-versatile.",
    ),
    "together": ProviderSpec(
        slug="together",
        label="Together AI",
        base_url="https://api.together.xyz/v1",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        key_hint="Models look like meta-llama/Llama-3.3-70B-Instruct-Turbo.",
    ),
}


@dataclass(frozen=True)
class LLMCredential:
    """Everything `app.llm` needs to make one call. Carries the secret, so it
    must never be logged or serialised — `__repr__` is suppressed below."""

    api_key: str
    base_url: str
    provider: str
    model: str | None
    is_user_supplied: bool

    def __repr__(self) -> str:  # pragma: no cover - defensive
        # A stray repr() in a log line or a traceback would otherwise print
        # the user's provider key.
        return (
            f"LLMCredential(provider={self.provider!r}, model={self.model!r}, "
            f"is_user_supplied={self.is_user_supplied!r}, api_key=<redacted>)"
        )

    @property
    def is_openrouter(self) -> bool:
        """OpenRouter-only request extras (`models`, `provider`, `reasoning`)
        are a 400 on api.openai.com and Groq, so `app.llm` gates on this."""
        return self.provider == OPENROUTER


def platform_credential() -> LLMCredential | None:
    """Our own key, or None when the operator has not configured one."""
    if not settings.OPENROUTER_API_KEY:
        return None
    return LLMCredential(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        provider=OPENROUTER,
        # None means "app.llm applies the per-call-site env override, then
        # OPENROUTER_MODEL" — the existing platform behaviour.
        model=None,
        is_user_supplied=False,
    )


def user_credential(db: Session, user_id: uuid.UUID | None) -> LLMCredential | None:
    """The user's own credential, or None if they have none (or the feature
    is off, or their stored key can no longer be decrypted)."""
    if user_id is None or not byo_llm_enabled():
        return None
    row = db.get(UserLLMCredential, user_id)
    if row is None:
        return None
    spec = PROVIDERS.get(row.provider)
    if spec is None:
        # A provider was removed from the allowlist after the row was written.
        logger.warning("Stored LLM credential names unknown provider %r", row.provider)
        return None
    try:
        api_key = decrypt_secret(row.encrypted_api_key)
    except SecretsUnavailable:
        # Encryption key rotated without re-encrypting. Fall back to the
        # platform route rather than failing the user's upload.
        logger.warning("Could not decrypt stored LLM credential for user %s", user_id)
        return None
    return LLMCredential(
        api_key=api_key,
        base_url=spec.base_url,
        provider=spec.slug,
        model=row.model or spec.default_model,
        is_user_supplied=True,
    )


def resolve_for_user(db: Session, user_id: uuid.UUID | None) -> LLMCredential | None:
    """The credential this user's LLM calls should use: their own if they have
    one, else the platform's, else None (no LLM is reachable at all)."""
    return user_credential(db, user_id) or platform_credential()


def llm_available_for(db: Session, user_id: uuid.UUID | None) -> bool:
    """True when *this* user can reach a model — including the case where the
    platform key is empty but they brought their own."""
    return resolve_for_user(db, user_id) is not None
