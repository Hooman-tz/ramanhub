"""Abstract summary + keyword extraction via the Anthropic API.

Same security posture as `app.ingestion.llm_fallback`: the model reply is
*forced* into a single tool call and always validated through a pydantic
model before use. A schema violation or API error raises `EnrichmentError`
and nothing is persisted.

Callers MUST check `settings.ANTHROPIC_API_KEY` and skip this module when it
is empty (the key is empty in local dev and the test env).
"""
from __future__ import annotations

import json
from typing import Any

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app.config import settings

MODEL_ID = "claude-sonnet-5"

_TOOL_NAME = "emit_summary"

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
    "research audience. Call the `emit_summary` tool exactly once. The "
    "summary must be plain language, 2-3 sentences, and at most 600 "
    "characters. Provide at most 8 lowercased keywords."
)


class AbstractSummary(BaseModel):
    summary: str = Field(max_length=600)
    keywords: list[str] = Field(default_factory=list, max_length=8)


class EnrichmentError(Exception):
    """Raised when the model reply cannot be validated into an
    `AbstractSummary`, or the API call fails. Callers must treat this as a
    non-fatal skip — never persist partial enrichment."""


def _extract_tool_input(message: Any) -> dict:
    for block in message.content:
        if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
            return block.input
    raise EnrichmentError("Model did not return the expected tool call")


async def summarize_abstract(text: str) -> AbstractSummary:
    if not settings.ANTHROPIC_API_KEY:
        raise EnrichmentError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    try:
        message = await client.messages.create(
            model=MODEL_ID,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            tools=[
                {
                    "name": _TOOL_NAME,
                    "description": "Record the abstract summary and keywords.",
                    "input_schema": _TOOL_INPUT_SCHEMA,
                }
            ],
            tool_choice={"type": "tool", "name": _TOOL_NAME},
            messages=[{"role": "user", "content": f"Abstract:\n\n{text}"}],
        )
    except anthropic.APIError as exc:
        raise EnrichmentError(f"Anthropic API call failed: {exc}") from exc

    tool_input = _extract_tool_input(message)
    try:
        if isinstance(tool_input, str):
            tool_input = json.loads(tool_input)
        summary = AbstractSummary.model_validate(tool_input)
    except (ValidationError, json.JSONDecodeError, TypeError) as exc:
        raise EnrichmentError(f"LLM tool output failed schema validation: {exc}") from exc

    summary.keywords = [k.strip().lower() for k in summary.keywords if k and k.strip()][:8]
    return summary
