"""Tests for app.llm — the single shared OpenRouter client.

The `AsyncOpenAI` class is patched in every test; no real network call is
made.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from app import llm
from app.llm import LLMError, complete_json, llm_configured

_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def _run(coro):
    return asyncio.run(coro)


def _resp(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _fake_openai(create: AsyncMock):
    client = MagicMock()
    client.chat.completions.create = create
    return patch("app.llm.AsyncOpenAI", return_value=client)


# ---------------------------------------------------------------------------
# llm_configured
# ---------------------------------------------------------------------------


def test_llm_configured_false_when_key_empty(monkeypatch):
    monkeypatch.setattr(llm.settings, "OPENROUTER_API_KEY", "")
    assert llm_configured() is False


def test_llm_configured_true_when_key_set(monkeypatch):
    monkeypatch.setattr(llm.settings, "OPENROUTER_API_KEY", "sk-or-xxx")
    assert llm_configured() is True


# ---------------------------------------------------------------------------
# complete_json
# ---------------------------------------------------------------------------


def test_complete_json_happy_path():
    create = AsyncMock(return_value=_resp('{"summary": "hello world"}'))
    with _fake_openai(create):
        out = _run(
            complete_json(system="sys", user="usr", schema=_SCHEMA)
        )
    assert out == {"summary": "hello world"}
    create.assert_awaited_once()


def test_complete_json_retries_once_on_bad_json_then_succeeds():
    create = AsyncMock(
        side_effect=[
            _resp("not json at all"),
            _resp('{"summary": "recovered"}'),
        ]
    )
    with _fake_openai(create):
        out = _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
    assert out == {"summary": "recovered"}
    assert create.await_count == 2


def test_complete_json_raises_llmerror_when_still_bad_after_retry():
    create = AsyncMock(side_effect=[_resp("nope"), _resp("still nope")])
    with _fake_openai(create), pytest.raises(LLMError):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
    assert create.await_count == 2


def test_complete_json_missing_required_key_raises_llmerror():
    create = AsyncMock(return_value=_resp('{"other": 1}'))
    with _fake_openai(create), pytest.raises(LLMError):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))


def test_complete_json_wraps_api_error():
    create = AsyncMock(
        side_effect=openai.APIError("boom", request=None, body=None)
    )
    with _fake_openai(create), pytest.raises(LLMError):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))


def test_complete_json_wraps_connection_error():
    create = AsyncMock(side_effect=openai.APIConnectionError(request=None))
    with _fake_openai(create), pytest.raises(LLMError):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
