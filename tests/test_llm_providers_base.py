"""Tests for the LLM provider base classes."""

from __future__ import annotations

import pytest

from gentlebot.llm.providers.base import (
    Message,
    ToolCall,
    GenerationResult,
    LLMProvider,
)


class TestMessage:
    """Tests for the Message dataclass."""

    def test_basic_message(self) -> None:
        msg = Message(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.name is None
        assert msg.tool_calls is None

    def test_to_dict(self) -> None:
        msg = Message(role="user", content="Hello")
        d = msg.to_dict()
        assert d == {"role": "user", "content": "Hello"}

    def test_to_dict_with_name(self) -> None:
        msg = Message(role="user", content="Hello", name="Alice")
        d = msg.to_dict()
        assert d["name"] == "Alice"

    def test_from_dict(self) -> None:
        d = {"role": "assistant", "content": "Hi there"}
        msg = Message.from_dict(d)
        assert msg.role == "assistant"
        assert msg.content == "Hi there"

    def test_from_dict_with_tool_calls(self) -> None:
        d = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "name": "calculate", "arguments": {"expression": "2+2"}}
            ],
        }
        msg = Message.from_dict(d)
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "calculate"


class TestToolCall:
    """Tests for the ToolCall dataclass."""

    def test_basic_tool_call(self) -> None:
        tc = ToolCall(id="call_1", name="calculate", arguments={"expression": "2+2"})
        assert tc.id == "call_1"
        assert tc.name == "calculate"
        assert tc.arguments == {"expression": "2+2"}

    def test_to_dict(self) -> None:
        tc = ToolCall(id="call_1", name="calculate", arguments={"expression": "2+2"})
        d = tc.to_dict()
        assert d == {
            "id": "call_1",
            "name": "calculate",
            "arguments": {"expression": "2+2"},
        }

    def test_from_dict(self) -> None:
        d = {"id": "call_1", "name": "web_search", "arguments": {"query": "test"}}
        tc = ToolCall.from_dict(d)
        assert tc.id == "call_1"
        assert tc.name == "web_search"


class TestGenerationResult:
    """Tests for the GenerationResult dataclass."""

    def test_basic_result(self) -> None:
        result = GenerationResult(text="Hello, world!")
        assert result.text == "Hello, world!"
        assert result.tool_calls == []
        assert result.usage is None

    def test_has_tool_calls(self) -> None:
        result = GenerationResult(text="")
        assert result.has_tool_calls is False

        result = GenerationResult(
            text="",
            tool_calls=[ToolCall(id="1", name="test", arguments={})],
        )
        assert result.has_tool_calls is True

    def test_with_usage(self) -> None:
        result = GenerationResult(
            text="Hello",
            usage={"input_tokens": 10, "output_tokens": 5},
        )
        assert result.usage["input_tokens"] == 10
        assert result.usage["output_tokens"] == 5


class TestLLMProviderInterface:
    """Tests to verify the LLMProvider interface requirements."""

    def test_abstract_methods(self) -> None:
        # Verify that LLMProvider cannot be instantiated directly
        with pytest.raises(TypeError):
            LLMProvider()

    def test_estimate_tokens_default(self) -> None:
        # Create a concrete implementation to test default methods
        class ConcreteProvider(LLMProvider):
            @property
            def name(self) -> str:
                return "test"

            def generate(self, *args, **kwargs):
                return GenerationResult(text="test")

            def convert_tool_schema(self, tool):
                return {}

        provider = ConcreteProvider()

        # Test default token estimation
        assert provider.estimate_tokens("Hello") >= 1
        assert provider.estimate_tokens("") == 0
