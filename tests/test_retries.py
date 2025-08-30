"""Tests for the retry helper."""
from __future__ import annotations

import types

import pytest

from gentlebot.infra.retries import call_with_backoff


class DummyError(Exception):
    """Exception carrying a mock HTTP response."""

    def __init__(self, status_code: int) -> None:
        self.response = types.SimpleNamespace(status_code=status_code)


def test_no_retry_on_429() -> None:
    """A 429 error should not be retried."""
    calls = 0

    def fn() -> None:
        nonlocal calls
        calls += 1
        raise DummyError(429)

    with pytest.raises(DummyError):
        call_with_backoff(fn)
    assert calls == 1


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

