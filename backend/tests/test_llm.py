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
from app.llm_credentials import LLMCredential

_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
}


def _run(coro):
    return asyncio.run(coro)


def _resp(content: str, finish_reason: str = "stop", reasoning_tokens: int | None = None):
    """A minimal chat-completion stand-in.

    `finish_reason` matters: "length" is how a provider reports that the token
    budget ran out mid-reply, which `complete_json` must treat as a budget
    failure rather than as malformed output.
    """
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=50,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning_tokens),
        ),
    )


def _fake_openai(create: AsyncMock):
    client = MagicMock()
    client.chat.completions.create = create
    return patch("app.llm.AsyncOpenAI", return_value=client)


@pytest.fixture(autouse=True)
def _platform_key(monkeypatch):
    """`complete_json` resolves a credential before it calls anything, so the
    tests that exercise the default route need a platform key to exist.
    Without this the suite only passes on a machine whose `.env` happens to
    carry a real key. Tests asserting the no-key behaviour override it.
    """
    monkeypatch.setattr(llm.settings, "OPENROUTER_API_KEY", "sk-or-test")


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


# ---------------------------------------------------------------------------
# Truncation: a reasoning model spends `max_tokens` on its chain of thought and
# the JSON arrives cut in half. Retrying that verbatim at temperature 0
# reproduces it exactly, so the retry has to buy more room instead.
# ---------------------------------------------------------------------------


def test_complete_json_retries_truncated_reply_with_a_bigger_budget():
    create = AsyncMock(
        side_effect=[
            _resp('{"summary": "hel', finish_reason="length", reasoning_tokens=762),
            _resp('{"summary": "complete"}'),
        ]
    )
    with _fake_openai(create):
        out = _run(complete_json(system="sys", user="usr", schema=_SCHEMA, max_tokens=1024))
    assert out == {"summary": "complete"}
    assert create.await_count == 2
    first, second = create.await_args_list
    assert first.kwargs["max_tokens"] == 1024
    assert second.kwargs["max_tokens"] == 4096
    # A truncated reply is a budget problem: correcting the model would waste
    # the retry, so the message list must be unchanged.
    assert len(second.kwargs["messages"]) == 2


def test_complete_json_truncated_twice_reports_the_budget_not_bad_json():
    create = AsyncMock(
        side_effect=[
            _resp('{"summ', finish_reason="length", reasoning_tokens=900),
            _resp('{"summ', finish_reason="length", reasoning_tokens=3900),
        ]
    )
    with _fake_openai(create), pytest.raises(LLMError) as excinfo:
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA, max_tokens=1024))
    message = str(excinfo.value)
    assert "truncated" in message
    assert "max_tokens=4096" in message


def test_complete_json_escalation_is_capped():
    create = AsyncMock(
        side_effect=[
            _resp("{", finish_reason="length"),
            _resp('{"summary": "ok"}'),
        ]
    )
    with _fake_openai(create):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA, max_tokens=4096))
    assert create.await_args_list[1].kwargs["max_tokens"] == 8192


def test_complete_json_bad_json_retry_also_gets_more_room():
    create = AsyncMock(side_effect=[_resp("not json"), _resp('{"summary": "ok"}')])
    with _fake_openai(create):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA, max_tokens=1024))
    second = create.await_args_list[1]
    assert second.kwargs["max_tokens"] == 2048
    # Malformed (not truncated) output does get the corrective turn.
    assert len(second.kwargs["messages"]) == 3


# ---------------------------------------------------------------------------
# Lenient recovery: models wrap the object in a fence or a sentence of
# preamble even when told not to. Recovering costs nothing; a retry costs a
# call.
# ---------------------------------------------------------------------------


def test_complete_json_recovers_a_fenced_object_without_retrying():
    create = AsyncMock(return_value=_resp('```json\n{"summary": "fenced"}\n```'))
    with _fake_openai(create):
        out = _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
    assert out == {"summary": "fenced"}
    create.assert_awaited_once()


def test_complete_json_recovers_an_object_wrapped_in_prose():
    create = AsyncMock(
        return_value=_resp('Sure! Here is the JSON:\n{"summary": "a}b"}\nHope that helps.')
    )
    with _fake_openai(create):
        out = _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
    # The brace inside the string value must not end the object early.
    assert out == {"summary": "a}b"}
    create.assert_awaited_once()


def test_complete_json_non_object_json_is_not_retried():
    create = AsyncMock(return_value=_resp("[1, 2, 3]"))
    with _fake_openai(create), pytest.raises(LLMError, match="not a JSON object"):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
    create.assert_awaited_once()


def test_complete_json_asks_for_low_reasoning_effort():
    """Reasoning tokens come out of the same budget as the answer, so every
    call asks the provider to keep deliberation cheap."""
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
    assert create.await_args.kwargs["extra_body"]["reasoning"] == {"effort": "low"}


def test_complete_json_unwraps_a_single_key_envelope():
    """Models sometimes wrap the answer in a key named after the thing asked
    for. The payload is right; only the envelope is wrong."""
    create = AsyncMock(return_value=_resp('{"result": {"summary": "wrapped"}}'))
    with _fake_openai(create):
        out = _run(complete_json(system="sys", user="usr", schema=_SCHEMA))
    assert out == {"summary": "wrapped"}
    create.assert_awaited_once()


def test_complete_json_still_rejects_a_reply_missing_required_keys():
    create = AsyncMock(return_value=_resp('{"result": {"nothing": "useful"}}'))
    with _fake_openai(create), pytest.raises(LLMError, match="missing required keys"):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))


# ---------------------------------------------------------------------------
# free-model routing (OpenRouter-only request extras)
# ---------------------------------------------------------------------------


def _openrouter_credential(model=None):
    return LLMCredential(
        api_key="sk-or-test",
        base_url="https://openrouter.ai/api/v1",
        provider="openrouter",
        model=model,
        is_user_supplied=False,
    )


def _user_credential(provider="openai", model="gpt-4o-mini"):
    return LLMCredential(
        api_key="sk-user-test",
        base_url="https://api.openai.com/v1",
        provider=provider,
        model=model,
        is_user_supplied=True,
    )


def test_fallback_models_are_sent_as_a_priority_list(monkeypatch):
    """The free router can hand back a model that is down or rate-limited;
    `models` is what lets OpenRouter move to the next one instead of failing
    the call."""
    monkeypatch.setattr(
        llm.settings, "OPENROUTER_FALLBACK_MODELS", "a/one:free, b/two:free ,, c/three:free"
    )
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(
            complete_json(
                system="sys", user="usr", schema=_SCHEMA, credential=_openrouter_credential()
            )
        )
    extra = create.await_args.kwargs["extra_body"]
    assert extra["models"] == ["a/one:free", "b/two:free", "c/three:free"]
    assert extra["provider"] == {"require_parameters": True}


def test_the_primary_model_is_not_repeated_in_the_fallback_list(monkeypatch):
    monkeypatch.setattr(llm.settings, "OPENROUTER_MODEL", "openrouter/free")
    monkeypatch.setattr(
        llm.settings, "OPENROUTER_FALLBACK_MODELS", "openrouter/free,b/two:free"
    )
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(
            complete_json(
                system="sys", user="usr", schema=_SCHEMA, credential=_openrouter_credential()
            )
        )
    assert create.await_args.kwargs["extra_body"]["models"] == ["b/two:free"]


def test_no_fallback_key_sent_when_none_are_configured(monkeypatch):
    monkeypatch.setattr(llm.settings, "OPENROUTER_FALLBACK_MODELS", "")
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(
            complete_json(
                system="sys", user="usr", schema=_SCHEMA, credential=_openrouter_credential()
            )
        )
    assert "models" not in create.await_args.kwargs["extra_body"]


def test_require_parameters_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(llm.settings, "OPENROUTER_REQUIRE_PARAMETERS", False)
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(
            complete_json(
                system="sys", user="usr", schema=_SCHEMA, credential=_openrouter_credential()
            )
        )
    assert "provider" not in create.await_args.kwargs["extra_body"]


def test_openrouter_extras_are_never_sent_to_another_provider(monkeypatch):
    """`models`, `provider` and `reasoning` are OpenRouter body fields.
    api.openai.com and Groq reject unknown top-level params with a 400, so a
    user who brought their own non-OpenRouter key would see every call fail."""
    monkeypatch.setattr(llm.settings, "OPENROUTER_FALLBACK_MODELS", "a/one:free")
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(
            complete_json(
                system="sys", user="usr", schema=_SCHEMA, credential=_user_credential()
            )
        )
    assert "extra_body" not in create.await_args.kwargs


# ---------------------------------------------------------------------------
# per-user credentials
# ---------------------------------------------------------------------------


def test_a_user_credential_selects_its_own_endpoint_key_and_model():
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    client = MagicMock()
    client.chat.completions.create = create
    with patch("app.llm.AsyncOpenAI", return_value=client) as ctor:
        _run(
            complete_json(
                system="sys",
                user="usr",
                schema=_SCHEMA,
                credential=_user_credential(model="gpt-4o"),
            )
        )
    assert ctor.call_args.kwargs["base_url"] == "https://api.openai.com/v1"
    assert ctor.call_args.kwargs["api_key"] == "sk-user-test"
    assert create.await_args.kwargs["model"] == "gpt-4o"


def test_a_call_site_model_override_does_not_beat_the_users_choice():
    """`model=` is a per-call-site preference for the platform key. A user who
    stored a key also chose a model, and an OpenRouter slug would be
    meaningless on their provider."""
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(
            complete_json(
                system="sys",
                user="usr",
                schema=_SCHEMA,
                model="openai/gpt-4o-mini",
                credential=_user_credential(model="llama-3.3-70b-versatile"),
            )
        )
    assert create.await_args.kwargs["model"] == "llama-3.3-70b-versatile"


def test_a_call_site_model_override_still_applies_to_the_platform_key():
    create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with _fake_openai(create):
        _run(
            complete_json(
                system="sys",
                user="usr",
                schema=_SCHEMA,
                model="some/ingestion-model",
                credential=_openrouter_credential(),
            )
        )
    assert create.await_args.kwargs["model"] == "some/ingestion-model"


def test_attribution_headers_are_openrouter_only():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=_resp('{"summary": "ok"}'))
    with patch("app.llm.AsyncOpenAI", return_value=client) as ctor:
        _run(
            complete_json(
                system="sys", user="usr", schema=_SCHEMA, credential=_user_credential()
            )
        )
    assert ctor.call_args.kwargs["default_headers"] == {}


def test_no_credential_and_no_platform_key_is_an_llm_error(monkeypatch):
    monkeypatch.setattr(llm.settings, "OPENROUTER_API_KEY", "")
    with pytest.raises(LLMError, match="No LLM credential"):
        _run(complete_json(system="sys", user="usr", schema=_SCHEMA))


def test_the_served_model_is_reported_not_the_router_slug(monkeypatch, caplog):
    """With `openrouter/free` the requested slug is a router, so naming it in
    an error is misleading — what actually answered is the useful fact."""
    monkeypatch.setattr(llm.settings, "OPENROUTER_FALLBACK_MODELS", "")
    truncated = _resp("{'not json", finish_reason="length", reasoning_tokens=700)
    truncated.model = "z-ai/glm-5.2:free"
    create = AsyncMock(return_value=truncated)
    with _fake_openai(create), pytest.raises(LLMError, match="z-ai/glm-5.2:free"):
        _run(
            complete_json(
                system="sys", user="usr", schema=_SCHEMA, credential=_openrouter_credential()
            )
        )
