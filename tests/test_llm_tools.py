"""Tests for the provider-agnostic tool definitions."""

from __future__ import annotations

import pytest

from gentlebot.llm.tools import (
    Tool,
    ToolParameter,
    ALL_TOOLS,
    WEB_SEARCH,
    CALCULATE,
    READ_FILE,
    GENERATE_IMAGE,
    get_tool,
    get_all_gemini_schemas,
    get_all_openai_schemas,
    get_all_claude_schemas,
)


class TestToolParameter:
    """Tests for ToolParameter dataclass."""

    def test_required_parameter(self) -> None:
        param = ToolParameter(
            name="query",
            type="string",
            description="Search query",
        )
        assert param.name == "query"
        assert param.required is True

    def test_optional_parameter(self) -> None:
        param = ToolParameter(
            name="limit",
            type="integer",
            description="Max results",
            required=False,
            default=10,
        )
        assert param.required is False
        assert param.default == 10


class TestTool:
    """Tests for Tool dataclass and schema conversions."""

    def test_to_gemini_schema(self) -> None:
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters=[
                ToolParameter("arg1", "string", "First argument"),
            ],
        )
        schema = tool.to_gemini_schema()

        assert schema["name"] == "test_tool"
        assert schema["description"] == "A test tool"
        assert "parameters" in schema
        assert schema["parameters"]["type"] == "object"
        assert "arg1" in schema["parameters"]["properties"]
        assert schema["parameters"]["required"] == ["arg1"]

    def test_to_openai_schema(self) -> None:
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters=[
                ToolParameter("arg1", "string", "First argument"),
            ],
        )
        schema = tool.to_openai_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "test_tool"
        assert "parameters" in schema["function"]

    def test_to_claude_schema(self) -> None:
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters=[
                ToolParameter("arg1", "string", "First argument"),
            ],
        )
        schema = tool.to_claude_schema()

        assert schema["name"] == "test_tool"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"

    def test_optional_parameters_not_in_required(self) -> None:
        tool = Tool(
            name="test",
            description="Test",
            parameters=[
                ToolParameter("required_arg", "string", "Required"),
                ToolParameter("optional_arg", "string", "Optional", required=False),
            ],
        )
        schema = tool.to_gemini_schema()

        assert "required_arg" in schema["parameters"]["required"]
        assert "optional_arg" not in schema["parameters"]["required"]


class TestBuiltinTools:
    """Tests for the built-in tool definitions."""

    def test_all_tools_count(self) -> None:
        assert len(ALL_TOOLS) == 4

    def test_web_search_definition(self) -> None:
        assert WEB_SEARCH.name == "web_search"
        assert len(WEB_SEARCH.parameters) == 2  # query, max_results

    def test_calculate_definition(self) -> None:
        assert CALCULATE.name == "calculate"
        assert len(CALCULATE.parameters) == 1  # expression

    def test_read_file_definition(self) -> None:
        assert READ_FILE.name == "read_file"
        assert len(READ_FILE.parameters) == 3  # path, limit, offset

    def test_generate_image_definition(self) -> None:
        assert GENERATE_IMAGE.name == "generate_image"
        assert len(GENERATE_IMAGE.parameters) == 1  # prompt

    def test_get_tool(self) -> None:
        assert get_tool("web_search") is WEB_SEARCH
        assert get_tool("calculate") is CALCULATE
        assert get_tool("read_file") is READ_FILE
        assert get_tool("generate_image") is GENERATE_IMAGE
        assert get_tool("nonexistent") is None


class TestSchemaGenerators:
    """Tests for bulk schema generation functions."""

    def test_get_all_gemini_schemas(self) -> None:
        schemas = get_all_gemini_schemas()
        assert len(schemas) == 1
        assert "function_declarations" in schemas[0]
        assert len(schemas[0]["function_declarations"]) == 4

    def test_get_all_openai_schemas(self) -> None:
        schemas = get_all_openai_schemas()
        assert len(schemas) == 4
        assert all(s["type"] == "function" for s in schemas)

    def test_get_all_claude_schemas(self) -> None:
        schemas = get_all_claude_schemas()
        assert len(schemas) == 4
        assert all("input_schema" in s for s in schemas)
