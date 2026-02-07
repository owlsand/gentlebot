"""Tests for LLM router tool-fallback and image modality error handling."""

from types import SimpleNamespace

import pytest

import gentlebot.llm.router as llm_router
from gentlebot.infra.quotas import RateLimited


def _ok_resp():
    return SimpleNamespace(
        text="ok", usage_metadata=SimpleNamespace(candidates_token_count=0)
    )


def _make_api_error(code, message):
    """Create an exception with a .code attribute, mimicking Gemini API errors."""
    exc = Exception(message)
    exc.code = code
    return exc


def test_retries_without_tools_on_400(monkeypatch):
    """When the model returns a 400 about unsupported function calling,
    the router should retry the same call without tool schemas."""
    router = llm_router.LLMRouter()
    calls = []

    def fake_generate(self, model, messages, **kwargs):
        calls.append({"model": model, "has_tools": "tools" in kwargs})
        if kwargs.get("tools"):
            raise _make_api_error(
                400,
                "Tool use with function calling is unsupported for model gemini-flash-latest",
            )
        return _ok_resp()

    monkeypatch.setattr(llm_router.GeminiClient, "generate", fake_generate)
    monkeypatch.setattr(llm_router, "call_with_backoff", lambda fn, **kw: fn())

    result = router.generate("general", [{"content": "hi"}])
    assert result == "ok"
    assert len(calls) == 2
    assert calls[0]["has_tools"] is True
    assert calls[1]["has_tools"] is False


def test_scheduled_fallback_then_tool_retry(monkeypatch):
    """Full cascade: scheduled → 429 → fallback to general → 400 tool error
    → retry without tools → success. This is the #369 chain."""
    router = llm_router.LLMRouter()
    scheduled_model = router.models["scheduled"]
    general_model = router.models["general"]
    calls = []

    def fake_generate(self, model, messages, **kwargs):
        calls.append({"model": model, "has_tools": "tools" in kwargs})
        if model == scheduled_model:
            exc = Exception("RESOURCE_EXHAUSTED")
            exc.response = SimpleNamespace(status_code=429)
            raise exc
        if model == general_model and kwargs.get("tools"):
            raise _make_api_error(
                400,
                "Tool use with function calling is unsupported for model gemini-flash-latest",
            )
        return _ok_resp()

    monkeypatch.setattr(llm_router.GeminiClient, "generate", fake_generate)
    monkeypatch.setattr(llm_router, "call_with_backoff", lambda fn, **kw: fn())

    result = router.generate("scheduled", [{"content": "hi"}])
    assert result == "ok"
    # scheduled attempt → general with tools → general without tools
    assert len(calls) == 3
    assert calls[0]["model"] == scheduled_model
    assert calls[1]["model"] == general_model
    assert calls[1]["has_tools"] is True
    assert calls[2]["model"] == general_model
    assert calls[2]["has_tools"] is False


def test_non_tool_400_not_swallowed(monkeypatch):
    """A 400 error that is NOT about function calling should propagate normally."""
    router = llm_router.LLMRouter()

    def fake_generate(self, model, messages, **kwargs):
        raise _make_api_error(400, "Invalid content: something else went wrong")

    monkeypatch.setattr(llm_router.GeminiClient, "generate", fake_generate)
    monkeypatch.setattr(llm_router, "call_with_backoff", lambda fn, **kw: fn())

    with pytest.raises(Exception, match="Invalid content"):
        router.generate("general", [{"content": "hi"}])


def test_generate_image_modality_error(monkeypatch):
    """generate_image() should raise ValueError with actionable message
    when the model returns a 400 modality error."""
    router = llm_router.LLMRouter()

    def fake_generate_image(self, model, prompt):
        raise _make_api_error(
            400,
            "400: Model does not support the requested response modalities: image,text",
        )

    monkeypatch.setattr(
        llm_router.GeminiClient, "generate_image", fake_generate_image
    )
    monkeypatch.setattr(llm_router, "call_with_backoff", lambda fn, **kw: fn())

    with pytest.raises(ValueError, match="does not support image generation"):
        router.generate_image("a cute cat")
