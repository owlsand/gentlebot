"""Tests for the GeminiProvider error-logging behaviour."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gentlebot.llm.providers.gemini import GeminiProvider


def _make_provider() -> GeminiProvider:
    """Create a GeminiProvider with a mocked client."""
    provider = GeminiProvider(api_key="test-key")
    provider.client = MagicMock()
    return provider


def test_429_logs_warning_not_error(caplog):
    """A 429 exception should emit a WARNING, not an ERROR."""
    provider = _make_provider()

    # Simulate a Gemini SDK 429 error (sets exc.code = 429)
    exc = Exception("Resource exhausted")
    exc.code = 429  # type: ignore[attr-defined]
    provider.client.models.generate_content.side_effect = exc

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(Exception, match="Resource exhausted"):
            provider.generate(
                model="gemini-2.5-flash",
                messages=[{"role": "user", "content": "hello"}],
            )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("429" in r.message for r in warning_records)
    assert not error_records


def test_500_logs_error(caplog):
    """A non-429 exception should still log at ERROR level."""
    provider = _make_provider()

    exc = Exception("Internal server error")
    exc.code = 500  # type: ignore[attr-defined]
    provider.client.models.generate_content.side_effect = exc

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(Exception, match="Internal server error"):
            provider.generate(
                model="gemini-2.5-flash",
                messages=[{"role": "user", "content": "hello"}],
            )

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("Gemini API call failed" in r.message for r in error_records)
