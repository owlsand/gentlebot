"""Tests for LLM router tool schema configuration."""

from __future__ import annotations

from gentlebot.llm.router import LLMRouter


def test_tool_schemas_include_google_search_grounding(monkeypatch) -> None:
    """_tool_schemas() should return both custom function declarations and native google_search."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    router = LLMRouter()
    schemas = router._tool_schemas()

    # Should contain at least two entries: function_declarations and google_search
    assert len(schemas) >= 2

    has_function_declarations = any("function_declarations" in s for s in schemas)
    has_google_search = any(s == {"google_search": {}} for s in schemas)

    assert has_function_declarations, "Expected function_declarations in schemas"
    assert has_google_search, "Expected native google_search grounding in schemas"


def test_tool_schemas_no_web_search_function(monkeypatch) -> None:
    """web_search should not appear as a custom function declaration."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    router = LLMRouter()
    schemas = router._tool_schemas()

    for schema in schemas:
        declarations = schema.get("function_declarations", [])
        for decl in declarations:
            assert decl["name"] != "web_search", (
                "web_search should not be in function_declarations; "
                "search is handled by native google_search grounding"
            )


def test_tool_handlers_no_web_search(monkeypatch) -> None:
    """_tool_handlers() should not include a web_search handler."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    router = LLMRouter()
    handlers = router._tool_handlers()
    assert "web_search" not in handlers
