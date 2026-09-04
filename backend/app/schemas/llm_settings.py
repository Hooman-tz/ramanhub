"""Request/response bodies for the bring-your-own-LLM-key endpoints.

The stored key is write-only across this whole surface: it is accepted on
`LLMKeyIn` and never appears on any response model. `LLMKeyStatus` carries
`key_last4` instead so the settings page can show the user which key is
stored without the server ever handing it back.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# Deliberately permissive — providers do not share a key format and invent new
# prefixes — but tight enough to reject a pasted URL, a JSON blob, or a value
# with a newline that would end up in an HTTP header.
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-.:]+$")
# Provider model slugs: "gpt-4o-mini", "z-ai/glm-5.2:free",
# "meta-llama/Llama-3.3-70B-Instruct-Turbo".
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]*$")


class LLMProviderOut(BaseModel):
    """One entry in the fixed provider allowlist, for populating the picker."""

    slug: str
    label: str
    default_model: str
    key_hint: str


class LLMKeyStatus(BaseModel):
    """What the settings page needs to render the "AI provider" card."""

    # False when LLM_KEY_ENCRYPTION_KEY is unset: the feature is off
    # server-side and the card should hide entirely.
    enabled: bool
    configured: bool
    provider: str | None = None
    provider_label: str | None = None
    model: str | None = None
    key_last4: str | None = None
    # What a user without their own key is currently routed to. Usually
    # `openrouter/free`, which is a router rather than a single model — see
    # `platform_model_varies`.
    platform_model: str | None = None
    # True when `platform_model` picks a different model per call, so the UI
    # can say so instead of implying a fixed choice.
    platform_model_varies: bool = False
    providers: list[LLMProviderOut] = Field(default_factory=list)


class LLMKeyIn(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    api_key: str = Field(min_length=8, max_length=512)
    # Omitted/blank means "the provider's default model".
    model: str | None = Field(default=None, max_length=128)

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, v: str) -> str:
        v = v.strip()
        if not _KEY_RE.match(v):
            raise ValueError("API key contains characters that are not valid in a key")
        return v

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not _MODEL_RE.match(v):
            raise ValueError("Model must look like a provider model slug")
        return v
