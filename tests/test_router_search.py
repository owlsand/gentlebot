"""Tests for the LLM router search helper."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
import requests

from gentlebot.llm import router as llm_router
from gentlebot.llm.router import LLMRouter
from gentlebot.infra import http as http_module


class DummyResponse:
    def __init__(
        self,
        *,
        json_data: dict | None = None,
        text: str = "",
        status_code: int = 200,
        headers: dict | None = None,
    ):
        self._json = json_data or {}
        self.text = text
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "text/html"}

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


@pytest.fixture(autouse=True)
def reset_http_session():
    """Reset the shared HTTP session before each test."""
    http_module.reset_sessions()
    yield
    http_module.reset_sessions()


def test_web_search_falls_back_to_jina(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the web search tool falls back to Jina when other methods fail."""

    router = LLMRouter()
    calls: list[str] = []

    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "demo")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx-demo")

    def fake_get(url: str, **_: object) -> DummyResponse:
        calls.append(url)
        if "googleapis" in url:
            return DummyResponse(json_data={"items": []})
        if "r.jina.ai" in url and "google.com" in url:
            return DummyResponse(
                text="Markdown Content:\n1. Example result\nSummary of the finding",
                status_code=200,
            )
        if "duckduckgo" in url:
            return DummyResponse(json_data={})
        raise AssertionError(f"unexpected fallback request: {url}")

    # Create a mock session with our fake_get
    mock_session = MagicMock()
    mock_session.get = fake_get
    monkeypatch.setattr(llm_router, "get_sync_session", lambda **_: mock_session)

    # Mock duckduckgo-search to return no results (simulating failure)
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text = MagicMock(return_value=[])

    with patch.dict(sys.modules, {"duckduckgo_search": MagicMock(DDGS=lambda: mock_ddgs)}):
        result = router._run_search({"query": "current year", "max_results": 2})

    assert "Example result" in result
    assert "Summary of the finding" in result
    assert any("googleapis" in call for call in calls)
    assert any("jina.ai" in call for call in calls)


def test_web_search_prefers_google_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Google Programmable Search should be used when keys are present."""

    router = LLMRouter()
    calls: list[str] = []

    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "demo")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx-demo")

    def fake_get(url: str, **_: object) -> DummyResponse:
        calls.append(url)
        if "googleapis" in url:
            return DummyResponse(
                json_data={
                    "items": [
                        {
                            "title": "Google result",
                            "snippet": "Details about the topic",
                            "link": "https://example.com",
                        }
                    ]
                }
            )
        if "example.com" in url:
            return DummyResponse(text="Full page content about the topic.")
        raise AssertionError("unexpected fallback request")

    # Create a mock session with our fake_get
    mock_session = MagicMock()
    mock_session.get = fake_get
    monkeypatch.setattr(llm_router, "get_sync_session", lambda **_: mock_session)

    result = router._run_search({"query": "current year", "max_results": 1})

    assert "Google result — https://example.com" in result
    assert "Full page content about the topic." in result
    assert "https://www.googleapis.com/customsearch/v1" in calls[0]
    assert any("example.com" in call for call in calls)


def test_web_search_uses_duckduckgo_search_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """DuckDuckGo search library should be used when Google is not configured."""

    router = LLMRouter()
    calls: list[str] = []

    # Clear Google API keys
    monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SEARCH_CX", raising=False)

    def fake_get(url: str, **_: object) -> DummyResponse:
        calls.append(url)
        if "example.com" in url:
            return DummyResponse(text="Full page content from DuckDuckGo result.")
        raise AssertionError(f"unexpected request: {url}")

    mock_session = MagicMock()
    mock_session.get = fake_get
    monkeypatch.setattr(llm_router, "get_sync_session", lambda **_: mock_session)

    # Mock duckduckgo-search to return results
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text = MagicMock(return_value=[
        {
            "title": "DDG Result",
            "body": "This is a DuckDuckGo search result snippet.",
            "href": "https://example.com/ddg",
        }
    ])

    with patch.dict(sys.modules, {"duckduckgo_search": MagicMock(DDGS=lambda: mock_ddgs)}):
        result = router._run_search({"query": "test query", "max_results": 1})

    assert "DDG Result — https://example.com/ddg" in result
    assert "Full page content from DuckDuckGo result." in result


def test_web_search_returns_error_detail_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web search should return detailed error info when all methods fail."""

    router = LLMRouter()

    # Clear Google API keys
    monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SEARCH_CX", raising=False)

    def fake_get(url: str, **_: object) -> DummyResponse:
        raise requests.exceptions.ConnectionError("Network error")

    mock_session = MagicMock()
    mock_session.get = fake_get
    monkeypatch.setattr(llm_router, "get_sync_session", lambda **_: mock_session)

    # Mock duckduckgo-search to fail
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
    mock_ddgs.__exit__ = MagicMock(return_value=False)
    mock_ddgs.text = MagicMock(return_value=[])

    with patch.dict(sys.modules, {"duckduckgo_search": MagicMock(DDGS=lambda: mock_ddgs)}):
        result = router._run_search({"query": "failing query", "max_results": 1})

    assert "No search results found" in result
    assert "Tried:" in result
