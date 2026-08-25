"""Tests for app.ingestion.llm_providers — the OpenRouter transport and
provider resolution.

Every HTTP call is mocked. Nothing here touches the network, and there is a
test below asserting the API key never escapes into an error message, because
error bodies from a gateway routinely echo the request back.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from app.config import settings
from app.ingestion.llm_providers import (
    AnthropicProvider,
    LLMProviderError,
    OpenRouterProvider,
    resolve_provider,
)

TOOL = "extract_raman_metadata"

CALL_KWARGS = {
    "system": "you extract metadata",
    "user_text": "#Laser: 785",
    "tool_name": TOOL,
    "tool_description": "Record it.",
    "tool_schema": {"type": "object", "properties": {"modality": {"type": "string"}}},
}


def _run(coro):
    return asyncio.run(coro)


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient. Records every request so tests can
    assert on the payload actually put on the wire."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        self.requests.append({"url": url, "headers": headers or {}, "json": json or {}})
        if not self._responses:
            raise AssertionError("more requests than canned responses")
        return self._responses.pop(0)


def _tool_response(arguments, name=TOOL):
    return _FakeResponse(
        payload={"choices": [{"message": {"tool_calls": [{"function": {"name": name, "arguments": arguments}}]}}]}
    )


def _with_client(fake):
    return patch("app.ingestion.llm_providers.httpx.AsyncClient", fake)


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """A fake key for every test in this module, so nothing depends on the
    developer's real .env and nothing can accidentally authenticate."""
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-TESTKEY-do-not-use", raising=False)
    return "sk-or-TESTKEY-do-not-use"


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


def test_arguments_arrive_as_a_json_string():
    """OpenRouter returns `function.arguments` as a STRING, unlike Anthropic's
    `tool_use.input` which is already an object. Getting this wrong is the
    single most likely way a naive port breaks."""
    fake = _FakeAsyncClient([_tool_response('{"modality": "raman", "laser_wavelength_nm": 785}')])

    with _with_client(fake):
        result = _run(OpenRouterProvider().call_tool(**CALL_KWARGS))

    assert result == {"modality": "raman", "laser_wavelength_nm": 785}


def test_arguments_may_also_arrive_as_an_object():
    fake = _FakeAsyncClient([_tool_response({"modality": "raman"})])

    with _with_client(fake):
        assert _run(OpenRouterProvider().call_tool(**CALL_KWARGS)) == {"modality": "raman"}


def test_http_200_with_an_error_body_is_still_an_error():
    """OpenRouter can return HTTP 200 with an `error` object in the body.
    Checking the status code alone reads that as success and fails
    confusingly much later."""
    fake = _FakeAsyncClient([_FakeResponse(payload={"error": {"message": "No allowed provider"}})])

    with _with_client(fake), pytest.raises(LLMProviderError, match="No allowed provider"):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))


def test_json_object_in_plain_content_is_accepted():
    """Small open-weights models sometimes ignore tool_choice and emit the
    object as ordinary content. Accepting it is free — the caller still
    validates — and it measurably raises the success rate on cheap models."""
    fake = _FakeAsyncClient(
        [_FakeResponse(payload={"choices": [{"message": {"content": '{"modality": "raman"}'}}]})]
    )

    with _with_client(fake):
        assert _run(OpenRouterProvider().call_tool(**CALL_KWARGS)) == {"modality": "raman"}


def test_prose_answer_is_rejected():
    fake = _FakeAsyncClient(
        [_FakeResponse(payload={"choices": [{"message": {"content": "Sure! The laser is 785nm."}}]})]
    )

    with _with_client(fake), pytest.raises(LLMProviderError, match="did not return"):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))


def test_unparseable_arguments_are_rejected():
    fake = _FakeAsyncClient([_tool_response("{not valid json")])

    with _with_client(fake), pytest.raises(LLMProviderError, match="not valid JSON"):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))


def test_no_choices_is_rejected():
    fake = _FakeAsyncClient([_FakeResponse(payload={"choices": []})])

    with _with_client(fake), pytest.raises(LLMProviderError, match="no choices"):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))


def test_http_error_status_is_reported():
    fake = _FakeAsyncClient([_FakeResponse(status_code=429, text="rate limited")])

    with _with_client(fake), pytest.raises(LLMProviderError, match="429"):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def test_the_api_key_never_appears_in_an_error(_key):
    """A gateway's error body often echoes the request, headers included.
    Any path that turns a response body into an exception message is a
    credential-leak path into logs and Sentry."""
    fake = _FakeAsyncClient(
        [_FakeResponse(status_code=401, text=f"Unauthorized for token {_key} on /chat/completions")]
    )

    with _with_client(fake), pytest.raises(LLMProviderError) as excinfo:
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))

    assert _key not in str(excinfo.value)
    assert "<redacted>" in str(excinfo.value)


def test_missing_key_fails_before_any_request():
    fake = _FakeAsyncClient([])

    with (
        patch.object(settings, "OPENROUTER_API_KEY", ""),
        _with_client(fake),
        pytest.raises(LLMProviderError, match="OPENROUTER_API_KEY"),
    ):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))

    assert fake.requests == []


# ---------------------------------------------------------------------------
# Request payload
# ---------------------------------------------------------------------------


def test_request_forces_the_tool_and_allows_model_fallback():
    fake = _FakeAsyncClient([_tool_response('{"modality": "raman"}')])

    with _with_client(fake):
        _run(
            OpenRouterProvider(
                model_id="primary/model", fallback_models=["backup/model"]
            ).call_tool(**CALL_KWARGS)
        )

    body = fake.requests[0]["json"]
    assert body["model"] == "primary/model"
    # OpenRouter's own routing fallback: a model that is down or refuses the
    # tool call falls through instead of failing the upload.
    assert body["models"] == ["primary/model", "backup/model"]
    # Without this, a request can be routed to a provider that silently
    # ignores `tools` and answers in prose.
    assert body["provider"]["require_parameters"] is True
    assert body["tool_choice"] == {"type": "function", "function": {"name": TOOL}}
    # Extraction, not composition — a creative sample here would just be a
    # chance to invent a laser wavelength.
    assert body["temperature"] == 0
    assert fake.requests[0]["headers"]["Authorization"].endswith("TESTKEY-do-not-use")


# ---------------------------------------------------------------------------
# Corrective retry (the reason cheap models are viable here)
# ---------------------------------------------------------------------------


def _reject_unless_has_vendor(payload):
    if "instrument_vendor" not in payload:
        raise ValueError("instrument_vendor: field required")


def test_a_schema_failure_is_retried_once_with_the_error_fed_back():
    fake = _FakeAsyncClient(
        [
            _tool_response('{"modality": "raman"}'),
            _tool_response('{"modality": "raman", "instrument_vendor": "Acme"}'),
        ]
    )

    with _with_client(fake):
        result = _run(
            OpenRouterProvider().call_tool(**CALL_KWARGS, validate=_reject_unless_has_vendor)
        )

    assert result["instrument_vendor"] == "Acme"
    assert len(fake.requests) == 2
    # The correction must name the offending field — a blind resend of an
    # identical prompt is just a second roll of the same dice.
    second = fake.requests[1]["json"]["messages"][1]["content"]
    assert "instrument_vendor: field required" in second
    assert "never guess" in second


def test_retry_is_not_attempted_without_a_validator():
    fake = _FakeAsyncClient([_tool_response('{"modality": "raman"}')])

    with _with_client(fake):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS))

    assert len(fake.requests) == 1


def test_exhausted_retries_raise_rather_than_return_bad_data():
    fake = _FakeAsyncClient(
        [_tool_response('{"modality": "raman"}'), _tool_response('{"modality": "raman"}')]
    )

    with _with_client(fake), pytest.raises(LLMProviderError, match="failed validation"):
        _run(OpenRouterProvider().call_tool(**CALL_KWARGS, validate=_reject_unless_has_vendor))

    assert len(fake.requests) == 2


# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------


def test_explicit_choices(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openrouter")
    assert isinstance(resolve_provider(), OpenRouterProvider)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    assert isinstance(resolve_provider(), AnthropicProvider)


def test_auto_prefers_openrouter_when_its_key_is_present(monkeypatch):
    """Deliberate ordering: a deployment that configured OpenRouter did so on
    purpose, whereas ANTHROPIC_API_KEY is often a leftover from .env.example."""
    monkeypatch.setattr(settings, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-whatever")
    assert isinstance(resolve_provider(), OpenRouterProvider)


def test_auto_falls_back_to_anthropic(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-whatever")
    assert isinstance(resolve_provider(), AnthropicProvider)


def test_auto_with_no_keys_is_an_actionable_error(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    with pytest.raises(LLMProviderError, match="No LLM provider configured"):
        resolve_provider()


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "gpt5-please")
    with pytest.raises(LLMProviderError, match="Unknown LLM_PROVIDER"):
        resolve_provider()
