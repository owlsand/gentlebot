"""Tests for the LLM router search helper."""

from __future__ import annotations

import pytest
import requests

from gentlebot.llm.router import LLMRouter


class DummyResponse:
    def __init__(self, *, json_data: dict | None = None, text: str = "", status_code: int = 200):
        self._json = json_data or {}
        self.text = text
        self.status_code = status_code

    def json(self) -> dict:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def test_web_search_falls_back_to_google_html(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the web search tool falls back when Google returns nothing."""

    router = LLMRouter()
    calls: list[str] = []

    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "demo")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "cx-demo")

    def fake_get(url: str, **_: object) -> DummyResponse:
        calls.append(url)
        if "googleapis" in url:
            return DummyResponse(json_data={"items": []})
        if "google.com" in url:
            return DummyResponse(
                text="Markdown Content:\n1. Example result\nSummary of the finding",
                status_code=200,
            )
        if "duckduckgo" in url:
            return DummyResponse(json_data={})
        raise AssertionError("unexpected fallback request")

    monkeypatch.setattr("gentlebot.llm.router.requests.get", fake_get)

    result = router._run_search({"query": "current year", "max_results": 2})

    assert "Example result Summary of the finding" in result
    assert any("googleapis" in call for call in calls)
    assert any("google.com" in call for call in calls)


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
        raise AssertionError("unexpected fallback request")

    monkeypatch.setattr("gentlebot.llm.router.requests.get", fake_get)

    result = router._run_search({"query": "current year", "max_results": 1})

    assert "Google result — Details about the topic — https://example.com" in result
    assert calls == ["https://www.googleapis.com/customsearch/v1"]
