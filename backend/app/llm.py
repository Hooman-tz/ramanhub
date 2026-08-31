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
"""
from __future__ import annotations

import json
import logging

import openai
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


def llm_configured() -> bool:
    """True when an OpenRouter key is set. Call sites must check this and
    skip LLM features (not error) when it returns False."""
    return bool(settings.OPENROUTER_API_KEY)


class LLMError(Exception):
    """Generic LLM failure: API error, timeout, non-JSON reply after one
    retry, or a reply missing schema-required keys. Call sites map this to
    their own error types."""


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.OPENROUTER_BASE_URL,
        api_key=settings.OPENROUTER_API_KEY,
        default_headers={
            "HTTP-Referer": settings.BACKEND_URL or "https://spectra-in.site",
            "X-Title": "Spectra Insight",
        },
        timeout=settings.INGESTION_PARSE_TIMEOUT_SECONDS,
    )


async def complete_json(
    *,
    system: str,
    user: str,
    schema: dict,
    model: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.0,
) -> dict:
    """Ask the model for a single JSON object matching `schema` and return it
    parsed. Raises `LLMError` on API failure, or on an invalid/incomplete
    reply that survives one retry."""
    model = model or settings.OPENROUTER_MODEL
    client = _client()

    system_content = (
        system
        + "\n\nRespond with ONLY a JSON object matching this JSON Schema:\n"
        + json.dumps(schema)
    )
    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user},
    ]

    async def _call() -> str:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except (openai.APIConnectionError, openai.APIError) as exc:
            raise LLMError(f"LLM API call failed: {exc}") from exc
        except TimeoutError as exc:
            raise LLMError("LLM API call timed out") from exc
        return resp.choices[0].message.content or ""

    raw = await _call()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        messages.append(
            {
                "role": "user",
                "content": "Your previous reply was not valid JSON. Return only the JSON object.",
            }
        )
        raw = await _call()
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMError("LLM reply was not valid JSON after one retry") from exc

    if not isinstance(parsed, dict):
        raise LLMError("LLM reply was not a JSON object")

    missing = [k for k in schema.get("required", []) if k not in parsed]
    if missing:
        raise LLMError(f"LLM reply missing required keys: {', '.join(missing)}")

    return parsed
