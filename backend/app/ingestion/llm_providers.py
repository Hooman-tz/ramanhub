"""Provider seam for the two LLM call sites: header metadata extraction
(`app.ingestion.llm_fallback`) and filename suggestion
(`app.routers.raw_files`).

Both sites ask the same shape of question — "call exactly this one tool, with
these arguments, and return nothing else" — so they share one interface here
rather than each hand-rolling a client.

## Why a seam rather than swapping the SDK

Anthropic and OpenRouter disagree about wire format (Anthropic's
`tools`/`input_schema`/`tool_use` blocks vs OpenAI-style
`tools`/`parameters`/`tool_calls`), and the response-shape differences are
exactly where a naive swap breaks quietly. Isolating them here means the
callers keep one shape, and — importantly — the *security boundary is
unchanged*: a provider returns a plain `dict` that has been through no
validation at all, and the caller is still the only thing that decides
whether it may reach the database.

## Why httpx rather than the `openai` SDK

OpenRouter speaks the OpenAI wire format, so the `openai` package would work.
`httpx` is already a dependency and this is one POST; adding an SDK for a
single endpoint is not worth the supply-chain surface.

## Secrets

The API key is read from settings at call time, sent in an `Authorization`
header, and never logged, never echoed into an exception message, and never
included in a `repr`. `_redact` exists so that response bodies — which can
contain a request echo — cannot leak it either.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

import anthropic
import httpx

from app.config import settings


class LLMProviderError(Exception):
    """Transport or shape failure talking to a model provider. Callers
    translate this into their own domain error — never let it escape raw,
    and never include the request payload in the message."""


class LLMProvider(Protocol):
    """Forced single-tool-call interface.

    `call_tool` returns the tool's arguments as a dict. It performs NO
    schema validation beyond "this is a JSON object" — validating the
    contents is the caller's job and must stay that way, because the caller
    is what knows which pydantic model the result has to satisfy.
    """

    model_id: str

    async def call_tool(
        self,
        *,
        system: str,
        user_text: str,
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int = 1024,
        validate: Callable[[dict], None] | None = None,
    ) -> dict: ...


def _redact(text: str) -> str:
    """Strip anything resembling the configured API key from text that is
    about to be raised or logged. Providers echo request fragments in error
    bodies often enough that this is worth doing unconditionally."""
    key = settings.OPENROUTER_API_KEY or settings.ANTHROPIC_API_KEY
    if key and len(key) > 8:
        text = text.replace(key, "<redacted>")
    return text


class AnthropicProvider:
    """Direct Anthropic API. This is the original code path, unchanged in
    behaviour — it is kept so an Anthropic key keeps working exactly as it
    did before the seam existed."""

    def __init__(self, model_id: str = "claude-sonnet-5") -> None:
        self.model_id = model_id

    async def call_tool(
        self,
        *,
        system: str,
        user_text: str,
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int = 1024,
        validate: Callable[[dict], None] | None = None,
    ) -> dict:
        client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        try:
            message = await client.messages.create(
                model=self.model_id,
                max_tokens=max_tokens,
                system=system,
                tools=[
                    {
                        "name": tool_name,
                        "description": tool_description,
                        "input_schema": tool_schema,
                    }
                ],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": user_text}],
            )
        except anthropic.APIError as exc:
            raise LLMProviderError(f"Anthropic API call failed: {_redact(str(exc))}") from exc

        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if validate is not None:
                    validate(payload)
                return payload
        raise LLMProviderError("Model did not return the expected tool call")


class OpenRouterProvider:
    """OpenRouter, via its OpenAI-compatible chat-completions endpoint.

    Three things here are not obvious and are load-bearing for the small
    open-weights models this defaults to:

    * **`models` routing array.** OpenRouter falls through the list when a
      model is unavailable or refuses, so one flaky provider doesn't fail an
      upload.
    * **`provider.require_parameters`.** Tool-calling support varies across
      the providers serving a given open model. Without this, a request can
      be routed to one that silently ignores `tools` and answers in prose.
    * **A retry that feeds the validation error back.** Small models get
      structured output wrong more often than frontier ones. One corrective
      round-trip recovers a large share of those without the cost of just
      using a bigger model.
    """

    def __init__(
        self,
        model_id: str | None = None,
        fallback_models: list[str] | None = None,
    ) -> None:
        self.model_id = model_id or settings.OPENROUTER_MODEL
        if fallback_models is None:
            fallback_models = [
                m.strip() for m in settings.OPENROUTER_FALLBACK_MODELS.split(",") if m.strip()
            ]
        self.fallback_models = fallback_models

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            # Attribution headers OpenRouter uses for its dashboard. Not
            # secrets, and not required, but they make usage legible.
            "HTTP-Referer": settings.FRONTEND_URL,
            "X-Title": "RamanHub",
        }

    def _payload(
        self,
        *,
        system: str,
        user_text: str,
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int,
    ) -> dict:
        models = [self.model_id, *self.fallback_models]
        return {
            "model": self.model_id,
            "models": models,
            "max_tokens": max_tokens,
            # Deterministic: this is extraction, not composition. A creative
            # sample here is just a chance to invent a laser wavelength.
            "temperature": 0,
            "provider": {"require_parameters": True},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool_description,
                        "parameters": tool_schema,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": tool_name}},
        }

    @staticmethod
    def _extract(data: Any, tool_name: str) -> dict:
        """Pull the tool arguments out of an OpenRouter response.

        Two shape hazards handled here:

        * OpenRouter can return **HTTP 200 with an `error` object** in the
          body instead of an HTTP error status. Checking status alone would
          read that as success and then fail confusingly downstream.
        * `function.arguments` is a **JSON string**, not an object — unlike
          Anthropic's `tool_use.input`.
        """
        if not isinstance(data, dict):
            raise LLMProviderError("OpenRouter returned a non-object response")

        error = data.get("error")
        if error:
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise LLMProviderError(f"OpenRouter error: {_redact(str(message))}")

        choices = data.get("choices") or []
        if not choices:
            raise LLMProviderError("OpenRouter returned no choices")

        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        for call in tool_calls:
            function = call.get("function") or {}
            if function.get("name") != tool_name:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    return json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise LLMProviderError(
                        f"Tool arguments were not valid JSON: {exc}"
                    ) from exc
            if isinstance(arguments, dict):
                return arguments
            raise LLMProviderError("Tool call had no usable arguments")

        # Last-ditch: some small open models ignore tool_choice and emit the
        # JSON object as ordinary content. Accepting that costs nothing —
        # the result still has to pass the caller's schema validation — and
        # it meaningfully raises the success rate on cheap models.
        content = message.get("content")
        if isinstance(content, str) and content.strip().startswith("{"):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

        raise LLMProviderError("Model did not return the expected tool call")

    async def call_tool(
        self,
        *,
        system: str,
        user_text: str,
        tool_name: str,
        tool_description: str,
        tool_schema: dict,
        max_tokens: int = 1024,
        validate: Callable[[dict], None] | None = None,
    ) -> dict:
        if not settings.OPENROUTER_API_KEY:
            raise LLMProviderError(
                "OPENROUTER_API_KEY is not set — cannot call OpenRouter. "
                "Set it in .env (OPENROUTER is accepted as an alias)."
            )

        attempts = 2 if validate is not None else 1
        correction: str | None = None
        last_error: Exception | None = None

        async with httpx.AsyncClient(
            base_url=settings.OPENROUTER_BASE_URL,
            timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
        ) as client:
            for attempt in range(attempts):
                text = user_text if correction is None else f"{user_text}\n\n{correction}"
                payload = self._payload(
                    system=system,
                    user_text=text,
                    tool_name=tool_name,
                    tool_description=tool_description,
                    tool_schema=tool_schema,
                    max_tokens=max_tokens,
                )
                try:
                    response = await client.post(
                        "/chat/completions", headers=self._headers(), json=payload
                    )
                except httpx.HTTPError as exc:
                    raise LLMProviderError(
                        f"OpenRouter request failed: {_redact(str(exc))}"
                    ) from exc

                if response.status_code >= 400:
                    raise LLMProviderError(
                        f"OpenRouter HTTP {response.status_code}: "
                        f"{_redact(response.text[:500])}"
                    )

                try:
                    data = response.json()
                except ValueError as exc:
                    raise LLMProviderError("OpenRouter returned non-JSON") from exc

                result = self._extract(data, tool_name)
                if validate is None:
                    return result

                try:
                    validate(result)
                    return result
                except Exception as exc:  # noqa: BLE001 - re-raised below
                    last_error = exc
                    if attempt + 1 >= attempts:
                        break
                    # Feed the failure back verbatim. Naming the offending
                    # field is what makes the second attempt better than a
                    # blind retry of an identical prompt.
                    correction = (
                        "Your previous tool call was rejected by schema "
                        f"validation with this error:\n{exc}\n"
                        "Call the tool again, corrected. Use null for any "
                        "field you are unsure about — never guess a value."
                    )

        raise LLMProviderError(
            f"Model output failed validation after {attempts} attempt(s): {last_error}"
        )


def resolve_provider() -> LLMProvider:
    """Pick a provider from settings.

    `auto` prefers OpenRouter when its key is present. That ordering is
    deliberate: a deployment that has configured OpenRouter has done so on
    purpose, whereas `ANTHROPIC_API_KEY` may be a leftover empty string from
    `.env.example`.
    """
    choice = (settings.LLM_PROVIDER or "auto").strip().lower()

    if choice == "openrouter":
        return OpenRouterProvider()
    if choice == "anthropic":
        return AnthropicProvider()
    if choice != "auto":
        raise LLMProviderError(
            f"Unknown LLM_PROVIDER {choice!r} — expected 'auto', 'openrouter' or 'anthropic'"
        )

    if settings.OPENROUTER_API_KEY:
        return OpenRouterProvider()
    if settings.ANTHROPIC_API_KEY:
        return AnthropicProvider()
    raise LLMProviderError(
        "No LLM provider configured — set OPENROUTER_API_KEY or ANTHROPIC_API_KEY in .env"
    )
