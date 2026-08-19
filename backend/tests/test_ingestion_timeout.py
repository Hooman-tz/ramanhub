"""Unit tests for app.ingestion.jobs.run_with_timeout — the wall-clock
timeout wrapper around parser execution (Module 5: "run header/spectrum
parsing in a resource-limited step so a malformed file can't crash or hang
the server"). No DB required; pure function over a fake callable."""
from __future__ import annotations

import time

import pytest

from app.ingestion.jobs import run_with_timeout


def _fast_parser(raw_bytes: bytes) -> str:
    return f"parsed:{len(raw_bytes)}"


def _slow_parser(raw_bytes: bytes) -> str:
    time.sleep(2)
    return "should not get here"


def _raising_parser(raw_bytes: bytes) -> str:
    raise ValueError("malformed input")


def test_run_with_timeout_returns_result_for_fast_call():
    result = run_with_timeout(_fast_parser, b"hello", timeout=5)
    assert result == "parsed:5"


def test_run_with_timeout_raises_timeout_error_for_slow_call():
    with pytest.raises(TimeoutError):
        run_with_timeout(_slow_parser, b"hello", timeout=0.1)


def test_run_with_timeout_propagates_the_wrapped_function_exception():
    with pytest.raises(ValueError, match="malformed input"):
        run_with_timeout(_raising_parser, b"hello", timeout=5)


def test_run_with_timeout_does_not_block_on_timeout():
    """The caller shouldn't be blocked waiting for the leaked/hung thread to
    finish — this test itself would hang if `run_with_timeout` waited for
    `_slow_parser`'s full 2s sleep instead of returning as soon as the 0.1s
    timeout elapses."""
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        run_with_timeout(_slow_parser, b"hello", timeout=0.1)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
