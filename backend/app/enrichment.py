"""Abstract summary + keyword extraction via the shared LLM client.

Same security posture as `app.ingestion.llm_fallback`: the model returns a
bare JSON object matching a JSON Schema and it is always validated through a
pydantic model before use. A schema violation or API error raises
`EnrichmentError` and nothing is persisted.

Callers MUST check `app.llm.llm_configured()` and skip this module when it
is False (no OpenRouter key in local dev and the test env).
"""
from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.llm import LLMError, complete_json, llm_configured

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


class EnrichmentError(Exception):
    """Raised when the model reply cannot be validated into an
    `AbstractSummary`, or the API call fails. Callers must treat this as a
    non-fatal skip — never persist partial enrichment."""


async def summarize_abstract(text: str) -> AbstractSummary:
    if not llm_configured():
        raise EnrichmentError("OPENROUTER_API_KEY is not configured")

    try:
        result = await complete_json(
            system=_SYSTEM_PROMPT,
            user=f"Abstract:\n\n{text}",
            schema=_TOOL_INPUT_SCHEMA,
            model=settings.OPENROUTER_ENRICHMENT_MODEL or None,
            max_tokens=1024,
        )
    except LLMError as exc:
        raise EnrichmentError(f"LLM call failed: {exc}") from exc

    try:
        summary = AbstractSummary.model_validate(result)
    except ValidationError as exc:
        raise EnrichmentError(f"LLM output failed schema validation: {exc}") from exc

    summary.keywords = [k.strip().lower() for k in summary.keywords if k and k.strip()][:8]
    return summary
