"""Tests for the retry helper."""
from __future__ import annotations

import types

import pytest

from gentlebot.infra.retries import _extract_status, call_with_backoff


class DummyError(Exception):
    """Exception carrying a mock HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.response = types.SimpleNamespace(status_code=status_code)


class GeminiStyleError(Exception):
    """Exception using ``code`` attribute (Gemini SDK style)."""

    def __init__(self, code: int) -> None:
        self.code = code


# -- _extract_status tests ---------------------------------------------------


def test_extract_status_response_style() -> None:
    exc = DummyError(429)
    assert _extract_status(exc) == 429


def test_extract_status_code_style() -> None:
    exc = GeminiStyleError(429)
    assert _extract_status(exc) == 429


def test_extract_status_none() -> None:
    assert _extract_status(Exception("plain")) is None


# -- call_with_backoff tests --------------------------------------------------


def test_retries_on_429() -> None:
    """A 429 error should be retried and succeed on subsequent attempt."""
    calls = 0

    def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < 2:
            raise DummyError(429)
        return "ok"

    result = call_with_backoff(fn, retries=2, base=0, max_delay=0)
    assert result == "ok"
    assert calls == 2


def test_429_exhausts_retries() -> None:
    """A persistent 429 should exhaust retries and raise."""
    calls = 0

    def fn() -> None:
        nonlocal calls
        calls += 1
        raise DummyError(429)

    with pytest.raises(DummyError):
        call_with_backoff(fn, retries=2, base=0, max_delay=0)
    assert calls == 3  # initial try + two retries


def test_raises_after_retries_exhausted() -> None:
    """After retries are exhausted the last exception is raised."""
    calls = 0

    def fn() -> None:
        nonlocal calls
        calls += 1
        raise DummyError(408)

    with pytest.raises(DummyError):
        call_with_backoff(fn, retries=2, base=0, max_delay=0)
    assert calls == 3  # initial try + two retries
