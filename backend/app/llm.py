"""Single shared LLM client for the backend.

Every LLM call in the app goes through `complete_json`, which routes to
OpenRouter (OpenAI-compatible API) so the operator can pick a
smaller/cheaper model via `OPENROUTER_MODEL` and the per-site overrides.

Security posture (shared by every call site): the model is asked for a bare
JSON object matching a supplied JSON Schema, the reply is parsed with
`json.loads`, a shallow required-keys check is applied, and the *real*
validation happens at the call site via a pydantic model. LLM output never
touches a file path, SQL string, or shell command.

Prompts and raw abstract/header text are never logged at INFO.

REASONING MODELS: on a reasoning model (gpt-oss, o-series, …) the chain of
thought is billed against `max_tokens`, so a budget sized for the answer
alone gets eaten before the JSON is finished and the reply arrives truncated
mid-string with `finish_reason == "length"`. That is a *budget* failure, not
a malformed-output failure, and retrying it verbatim at `temperature=0`
reproduces it exactly. `complete_json` therefore inspects `finish_reason`,
retries truncation with a larger budget (not a scolding message), and asks
OpenRouter for a low reasoning effort so the budget goes to the answer.
"""

from __future__ import annotations

import json
import logging

import openai
from openai import AsyncOpenAI

from app.config import settings
from app.llm_credentials import LLMCredential, platform_credential

logger = logging.getLogger(__name__)

# A retry after truncation gets this multiple of the original budget, capped
# at `MAX_TOKEN_CEILING`. Output here is always a small JSON object, so the
# ceiling exists to bound a runaway model, not to bound a legitimate answer.
_TOKEN_ESCALATION_FACTOR = 4
_MAX_TOKEN_CEILING = 8192

# Reasoning models are asked for the cheapest thinking that still answers, so
# the token budget is spent on the JSON rather than on deliberation. Ignored
# by OpenRouter for models that do not reason.
_REASONING_EFFORT = "low"


def llm_configured() -> bool:
    """True when an OpenRouter key is set. Call sites must check this and
    skip LLM features (not error) when it returns False."""
    return bool(settings.OPENROUTER_API_KEY)


class LLMError(Exception):
    """Generic LLM failure: API error, timeout, a reply truncated by the token
    budget, a non-JSON reply after one retry, or a reply missing
    schema-required keys. Call sites map this to their own error types."""


def _client(credential: LLMCredential) -> AsyncOpenAI:
    # The attribution headers are OpenRouter's leaderboard convention and mean
    # nothing elsewhere, so a user's own OpenAI/Groq call does not carry them.
    headers = (
        {
            "HTTP-Referer": settings.BACKEND_URL or "https://spectra-in.site",
            "X-Title": "Spectra Insight",
        }
        if credential.is_openrouter
        else {}
    )
    return AsyncOpenAI(
        base_url=credential.base_url,
        api_key=credential.api_key,
        default_headers=headers,
        timeout=settings.INGESTION_PARSE_TIMEOUT_SECONDS,
    )


def _openrouter_extras(primary: str) -> dict:
    """OpenRouter-specific request body fields.

    Never sent to another provider: api.openai.com, Groq and friends reject
    unknown top-level body params with a 400, so a user who brought their own
    non-OpenRouter key would see every call fail.

    `models` is a priority-ordered fallback list — OpenRouter moves down it on
    provider downtime, rate limiting, a context-length rejection, or a
    moderation refusal, and does not bill the failed attempt. That is what
    makes the free router survivable: any single free model being unavailable
    is now a routing detail rather than a failed ingestion.
    """
    extras: dict = {"reasoning": {"effort": _REASONING_EFFORT}}
    fallbacks = [slug for slug in settings.openrouter_fallback_models() if slug != primary]
    if fallbacks:
        extras["models"] = fallbacks
    if settings.OPENROUTER_REQUIRE_PARAMETERS:
        # Only route to providers that honour everything we sent — chiefly
        # `response_format`. One that silently ignores it answers in prose,
        # which costs a retry to find out.
        extras["provider"] = {"require_parameters": True}
    return extras


def _first_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` span in `text`, or None.

    Models routinely wrap the object in a ```json fence or a sentence of
    preamble even when told not to. Scanning for a balanced object recovers
    those replies instead of burning a retry on them. Braces inside JSON
    strings (and escaped quotes) are not counted.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


class _NotAnObject(Exception):
    """The reply was valid JSON but not a JSON object — a prompt/schema
    problem that a retry will not fix."""


def _parse_object(raw: str) -> dict | None:
    """Parse a reply that should be a bare JSON object.

    Returns the object, or None when the text cannot be read as JSON at all
    (the caller then decides whether to retry). Raises `_NotAnObject` when
    the reply parsed cleanly into a non-object.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        candidate = _first_json_object(text)
        if candidate is None:
            return None
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(parsed, dict):
        raise _NotAnObject
    return parsed


def _usage(resp) -> dict[str, int | None]:
    """Best-effort token counts for logging and error messages. Never raises —
    a provider that omits usage must not turn into a 500."""
    usage = getattr(resp, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
    }


async def complete_json(
    *,
    system: str,
    user: str,
    schema: dict,
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    credential: LLMCredential | None = None,
) -> dict:
    """Ask the model for a single JSON object matching `schema` and return it
    parsed. Raises `LLMError` on API failure, on a reply still truncated after
    a budget escalation, or on an invalid/incomplete reply that survives one
    retry.

    `credential` selects which key/endpoint/model to use — pass the result of
    `app.llm_credentials.resolve_for_user` so a user who brought their own key
    is routed to it. Omitting it falls back to the platform credential, so a
    call site that has no user context still works.

    `model` is a per-call-site preference and applies to the platform
    credential only: a user who supplied a key also chose (or defaulted) a
    model, and an OpenRouter slug is meaningless on another provider.
    """
    credential = credential or platform_credential()
    if credential is None:
        raise LLMError("No LLM credential is configured")
    resolved_model = (
        credential.model
        if credential.is_user_supplied
        else (model or settings.OPENROUTER_MODEL)
    )
    client = _client(credential)

    system_content = (
        system
        + "\n\nRespond with ONLY a JSON object matching this JSON Schema:\n"
        + json.dumps(schema)
    )
    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user},
    ]

    extra_body = _openrouter_extras(resolved_model) if credential.is_openrouter else None

    async def _call(budget: int) -> tuple[str, str | None, dict, str]:
        try:
            kwargs: dict = {
                "model": resolved_model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "max_tokens": budget,
                "temperature": temperature,
            }
            if extra_body is not None:
                kwargs["extra_body"] = extra_body
            resp = await client.chat.completions.create(**kwargs)
        except (openai.APIConnectionError, openai.APIError) as exc:
            raise LLMError(f"LLM API call failed: {exc}") from exc
        except TimeoutError as exc:
            raise LLMError("LLM API call timed out") from exc
        choice = resp.choices[0]
        # With `openrouter/free` the requested slug is a router, not a model:
        # what actually answered varies per call, and is the only useful thing
        # to name in a log line or a truncation error.
        served = getattr(resp, "model", None) or resolved_model
        return (
            choice.message.content or "",
            getattr(choice, "finish_reason", None),
            _usage(resp),
            served,
        )

    budget = max_tokens
    raw, finish_reason, usage, served_model = await _call(budget)
    try:
        parsed = _parse_object(raw)
    except _NotAnObject:
        raise LLMError("LLM reply was not a JSON object") from None

    if parsed is None:
        truncated = finish_reason == "length"
        logger.warning(
            "LLM reply unusable, retrying: requested=%s served=%s finish_reason=%s "
            "truncated=%s max_tokens=%s usage=%s",
            resolved_model,
            served_model,
            finish_reason,
            truncated,
            budget,
            usage,
        )
        logger.debug("Unusable LLM reply (%d chars): %.400r", len(raw), raw)
        if truncated:
            # A budget failure. Scolding the model changes nothing; room does.
            budget = min(max_tokens * _TOKEN_ESCALATION_FACTOR, _MAX_TOKEN_CEILING)
        else:
            messages.append(
                {
                    "role": "user",
                    "content": "Your previous reply was not valid JSON. Return only the JSON object.",
                }
            )
            # Give the correction room to land too — at temperature 0 an
            # identically-budgeted retry tends to reproduce the same reply.
            budget = min(max(max_tokens * 2, max_tokens), _MAX_TOKEN_CEILING)
        raw, finish_reason, usage, served_model = await _call(budget)
        try:
            parsed = _parse_object(raw)
        except _NotAnObject:
            raise LLMError("LLM reply was not a JSON object") from None
        if parsed is None:
            logger.warning(
                "LLM reply still unusable after retry: requested=%s served=%s "
                "finish_reason=%s max_tokens=%s usage=%s",
                resolved_model,
                served_model,
                finish_reason,
                budget,
                usage,
            )
            if finish_reason == "length":
                raise LLMError(
                    f"LLM reply was truncated by the token budget (model={served_model}, "
                    f"max_tokens={budget}, reasoning_tokens={usage['reasoning_tokens']}). "
                    "Raise max_tokens for this call site or use a non-reasoning model."
                )
            raise LLMError(
                f"LLM reply was not valid JSON after one retry "
                f"(model={served_model}, finish_reason={finish_reason})"
            )

    required = schema.get("required", [])
    missing = [k for k in required if k not in parsed]
    if missing and len(parsed) == 1:
        # Models sometimes wrap the answer in a single key named after the
        # thing being asked for (`{"layout": {...}}`). The payload is right;
        # only the envelope is wrong, and unwrapping it is free next to
        # another round trip.
        [inner] = parsed.values()
        if isinstance(inner, dict) and all(key in inner for key in required):
            logger.warning("Unwrapping single-key LLM reply envelope (model=%s)", model)
            return inner
    if missing:
        raise LLMError(f"LLM reply missing required keys: {', '.join(missing)}")

    return parsed
