"""Smoke tests for app.logging_config — structured JSON logging (Module 5).
Just verifies configure_logging() doesn't raise and that log_event() emits a
single well-formed JSON line with the expected keys; not a deep test, per
the task's scope (structured logging doesn't need exhaustive coverage)."""
from __future__ import annotations

import json
import logging

from app.logging_config import configure_logging, log_event


def test_configure_logging_does_not_raise():
    configure_logging()  # should not raise, and should be safe to call twice
    configure_logging()


def test_log_event_emits_one_json_line_with_expected_keys(capsys):
    configure_logging()
    logger = logging.getLogger("test.logging_config")

    log_event(logger, "test.event.happened", foo="bar", count=3)

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1

    payload = json.loads(lines[0])
    assert payload["event"] == "test.event.happened"
    assert payload["level"] == "INFO"
    assert "timestamp" in payload
    assert payload["context"] == {"foo": "bar", "count": 3}


def test_log_event_without_context_omits_context_key(capsys):
    configure_logging()
    logger = logging.getLogger("test.logging_config")

    log_event(logger, "test.event.no_context")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    payload = json.loads(lines[-1])
    assert payload["event"] == "test.event.no_context"
    assert "context" not in payload


def test_log_event_never_crashes_on_non_trivially_serializable_context(capsys):
    """`log_event` uses `default=str` for JSON serialization, so passing an
    object without special handling (e.g. a UUID) still produces valid
    JSON rather than raising."""
    import uuid

    configure_logging()
    logger = logging.getLogger("test.logging_config")

    log_event(logger, "test.event.uuid_context", some_id=uuid.uuid4())

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    payload = json.loads(lines[-1])  # should not raise
    assert "some_id" in payload["context"]
