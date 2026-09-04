"""Bring-your-own-LLM-key settings. Mounted at prefix `/v1`.

A user who stores a key here has every LLM-backed feature — ingestion header
parsing, file-structure detection, DOI abstract enrichment, filename
suggestions, and the lab consultant — routed to their own provider instead of
the platform's OpenRouter account. See `app.llm_credentials` for how the
choice is applied at each call site.

Three deliberate constraints:

* **The key is write-only.** No endpoint here returns it, and it is never
  logged. `key_last4` is the only fragment that leaves the server.
* **Providers are a fixed allowlist** with server-side base URLs
  (`app.llm_credentials.PROVIDERS`). A user-supplied endpoint would have the
  server issuing outbound requests to an address the user chose.
* **A key is verified before it is stored**, so the settings page can say
  "this works" rather than the user discovering it failed during an upload
  hours later.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_full_user
from app.config import settings
from app.db.session import get_db
from app.llm import LLMError, complete_json
from app.llm_credentials import PROVIDERS, LLMCredential
from app.models.user import User
from app.models.user_llm_credential import UserLLMCredential
from app.ratelimit import rate_limit_llm_key_write
from app.schemas.llm_settings import LLMKeyIn, LLMKeyStatus, LLMProviderOut
from app.security.secrets import (
    SecretsUnavailable,
    byo_llm_enabled,
    encrypt_secret,
    last4,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["llm-settings"])

# The smallest useful round trip: enough to prove the key authenticates and
# the model can return an object, without spending a real budget.
_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
}
_VERIFY_SYSTEM = "You are a connectivity check."
_VERIFY_USER = 'Reply with exactly {"ok": true}.'
_VERIFY_MAX_TOKENS = 512


def _provider_list() -> list[LLMProviderOut]:
    return [
        LLMProviderOut(
            slug=spec.slug,
            label=spec.label,
            default_model=spec.default_model,
            key_hint=spec.key_hint,
        )
        for spec in PROVIDERS.values()
    ]


# OpenRouter's routers pick a different model per request, so naming one
# would be a lie. Anything else is a concrete model.
_ROUTER_SLUGS = {"openrouter/free", "openrouter/auto"}


def _platform_model() -> tuple[str | None, bool]:
    slug = settings.OPENROUTER_MODEL if settings.OPENROUTER_API_KEY else None
    return slug, slug in _ROUTER_SLUGS


def _status(row: UserLLMCredential | None) -> LLMKeyStatus:
    platform_slug, varies = _platform_model()
    if row is None:
        return LLMKeyStatus(
            enabled=byo_llm_enabled(),
            configured=False,
            platform_model=platform_slug,
            platform_model_varies=varies,
            providers=_provider_list(),
        )
    spec = PROVIDERS.get(row.provider)
    return LLMKeyStatus(
        enabled=byo_llm_enabled(),
        configured=True,
        provider=row.provider,
        provider_label=spec.label if spec else row.provider,
        model=row.model or (spec.default_model if spec else None),
        key_last4=row.key_last4,
        platform_model=platform_slug,
        platform_model_varies=varies,
        providers=_provider_list(),
    )


def _require_enabled() -> None:
    if not byo_llm_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Bring-your-own-key is not available on this deployment "
                "(no encryption key is configured)."
            ),
        )


@router.get("/users/me/llm-key", response_model=LLMKeyStatus)
def get_llm_key(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> LLMKeyStatus:
    """Whether this user has stored a key, and which providers they may pick.

    Always 200, even when the feature is disabled — the client reads
    `enabled` and hides the card, rather than treating a 503 as an error.
    """
    return _status(db.get(UserLLMCredential, user.id))


@router.put("/users/me/llm-key", response_model=LLMKeyStatus)
async def set_llm_key(
    payload: LLMKeyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
    _: None = Depends(rate_limit_llm_key_write),
) -> LLMKeyStatus:
    """Store (or replace) this user's provider key, after verifying it works."""
    _require_enabled()

    spec = PROVIDERS.get(payload.provider)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider. Choose one of: {', '.join(PROVIDERS)}.",
        )

    model = payload.model or spec.default_model
    candidate = LLMCredential(
        api_key=payload.api_key,
        base_url=spec.base_url,
        provider=spec.slug,
        model=model,
        is_user_supplied=True,
    )
    try:
        await complete_json(
            system=_VERIFY_SYSTEM,
            user=_VERIFY_USER,
            schema=_VERIFY_SCHEMA,
            max_tokens=_VERIFY_MAX_TOKENS,
            credential=candidate,
        )
    except LLMError as exc:
        # `exc` carries the provider's own message (bad key, unknown model,
        # no credit), which is the useful thing to show. It never contains
        # the key — app.llm only ever interpolates the model name.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"That key did not work with {spec.label}: {exc}",
        ) from exc

    try:
        encrypted = encrypt_secret(payload.api_key)
    except SecretsUnavailable as exc:  # pragma: no cover - guarded by _require_enabled
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    row = db.get(UserLLMCredential, user.id)
    if row is None:
        row = UserLLMCredential(user_id=user.id)
    row.provider = spec.slug
    row.model = payload.model
    row.encrypted_api_key = encrypted
    row.key_last4 = last4(payload.api_key)
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Stored user LLM credential: user=%s provider=%s", user.id, spec.slug)
    return _status(row)


@router.delete("/users/me/llm-key", status_code=status.HTTP_204_NO_CONTENT)
def delete_llm_key(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_full_user),
) -> Response:
    """Forget this user's key. Their LLM features fall back to the platform
    route. Idempotent — deleting a key that is not there is a 204."""
    row = db.get(UserLLMCredential, user.id)
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
