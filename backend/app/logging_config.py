"""Structured (JSON) application logging.

Module 5 (Security, Logging & Operations) calls for structured JSON logs for
key events (upload, processing run, auth) — "plain rotated log files are
enough at this stage; no need for a full log-aggregation stack yet". This
module configures Python's stdlib `logging` to emit one JSON object per line
to stdout, which is both human-greppable and trivially ingested by any
hosting platform's log collector (Railway/Render/etc. all capture stdout).

Usage:
    from app.logging_config import configure_logging, log_event
    configure_logging()  # once, at process startup (app/main.py)

    logger = logging.getLogger(__name__)
    log_event(logger, "raw_file.upload.accepted", raw_file_id=str(raw_file.id))

Never pass secrets, tokens, or full file contents as context — IDs and
outcomes only.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    """Renders each LogRecord as a single JSON line: timestamp, level,
    event (the log message), and an optional `context` payload attached via
    `log_event`'s `extra={"context": ...}`."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        context = getattr(record, "context", None)
        if context:
            payload["context"] = context
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger to emit JSON lines to stdout.

    Idempotent — safe to call more than once (e.g. if the app factory or a
    test imports it repeatedly); each call simply replaces the root logger's
    handlers rather than stacking duplicates.
    """
    global _CONFIGURED
    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.handlers = [handler]

    _CONFIGURED = True


def is_configured() -> bool:
    return _CONFIGURED


def log_event(logger: logging.Logger, event: str, **context: Any) -> None:
    """Emit one structured log line.

    `event` should be a short, machine-parseable, dotted name (e.g.
    "auth.login.success", "raw_file.upload.accepted"). `context` is
    arbitrary JSON-serializable key/value data — IDs and outcomes only,
    never secrets, tokens, or full file contents.
    """
    logger.info(event, extra={"context": context})
