"""Abstract summary + keyword extraction via the shared LLM client.

Same security posture as `app.ingestion.llm_fallback`: the model returns a
bare JSON object matching a JSON Schema and it is always validated through a
pydantic model before use. A schema violation or API error raises
`EnrichmentError` and nothing is persisted.

Callers MUST check reachability first — `app.llm_credentials.llm_available_for`
when a user is in scope, `app.llm.llm_configured()` otherwise — and skip this
module when it is False (no OpenRouter key in local dev and the test env).

`credential` lets the caller route the abstract through the user's own
provider key; omitting it uses the platform key.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.llm import LLMError, complete_json
from app.llm_credentials import LLMCredential, platform_credential

_TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "2-3 sentence plain-language summary, at most 600 characters.",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "At most 8 lowercased topic keywords.",
        },
    },
    "required": ["summary", "keywords"],
}

_SYSTEM_PROMPT = (
    "You summarize scientific paper abstracts for a Raman-spectroscopy "
    "research audience. The summary must be plain language, 2-3 sentences, "
    "and at most 600 characters. Provide at most 8 lowercased keywords."
)


class AbstractSummary(BaseModel):
    summary: str = Field(max_length=600)
    keywords: list[str] = Field(default_factory=list, max_length=8)
    # Which model actually wrote this. Set by us after validation, never by
    # the model itself — under the free router the slug we asked for is not
    # the one that answered, and a reader deserves to know which it was.
    model: str | None = None


class EnrichmentError(Exception):
    """Raised when the model reply cannot be validated into an
    `AbstractSummary`, or the API call fails. Callers must treat this as a
    non-fatal skip — never persist partial enrichment."""


async def summarize_abstract(
    text: str, *, credential: LLMCredential | None = None
) -> AbstractSummary:
    if credential is None:
        credential = platform_credential()
    if credential is None:
        raise EnrichmentError("OPENROUTER_API_KEY is not configured")

    meta: dict = {}
    try:
        result = await complete_json(
            system=_SYSTEM_PROMPT,
            user=f"Abstract:\n\n{text}",
            schema=_TOOL_INPUT_SCHEMA,
            model=settings.OPENROUTER_ENRICHMENT_MODEL or None,
            max_tokens=1024,
            credential=credential,
            meta=meta,
        )
    except LLMError as exc:
        raise EnrichmentError(f"LLM call failed: {exc}") from exc

    try:
        summary = AbstractSummary.model_validate(result)
    except ValidationError as exc:
        raise EnrichmentError(f"LLM output failed schema validation: {exc}") from exc

    summary.keywords = [k.strip().lower() for k in summary.keywords if k and k.strip()][:8]
    summary.model = meta.get("served_model")
    return summary
