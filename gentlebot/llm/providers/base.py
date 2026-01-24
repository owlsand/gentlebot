"""Abstract base class for LLM providers.

This module defines the provider interface that all LLM implementations
must follow. It enables swapping providers (Gemini, Claude, OpenAI) without
changing the router or cog code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Message:
    """Provider-agnostic message format.

    Attributes:
        role: Message role - "user", "assistant", or "system"
        content: The message text content
        name: Optional name for the message sender
        tool_calls: List of tool invocations requested by the model
        tool_call_id: ID linking a tool result to its invocation
    """
    role: str
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List["ToolCall"]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create a Message from a dictionary."""
        tool_calls = None
        if data.get("tool_calls"):
            tool_calls = [ToolCall.from_dict(tc) for tc in data["tool_calls"]]
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            name=data.get("name"),
            tool_calls=tool_calls,
            tool_call_id=data.get("tool_call_id"),
        )


@dataclass
class ToolCall:
    """Represents a tool invocation request from the model.

    Attributes:
        id: Unique identifier for this tool call
        name: Name of the tool to invoke
        arguments: Arguments to pass to the tool
    """
    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        """Create a ToolCall from a dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            arguments=data.get("arguments", {}),
        )


@dataclass
class GenerationResult:
    """Provider-agnostic generation result.

    Attributes:
        text: The generated text response
        tool_calls: List of tool invocations requested
        usage: Token usage statistics (input, output, total)
        finish_reason: Why generation stopped (stop, length, tool_calls, etc.)
        raw_response: The original provider-specific response object
    """
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    raw_response: Any = None

    @property
    def has_tool_calls(self) -> bool:
        """Check if the response contains tool calls."""
        return bool(self.tool_calls)


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All LLM providers (Gemini, Claude, OpenAI, etc.) must implement this
    interface to work with the router.
    """

    @abstractmethod
    def generate(
        self,
        model: str,
        messages: List[Message],
        temperature: float = 0.6,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate a completion from the model.

        Args:
            model: Model identifier (e.g., "gemini-2.5-pro", "claude-3-opus")
            messages: List of conversation messages
            temperature: Sampling temperature (0.0 to 2.0)
            max_tokens: Maximum tokens to generate
            tools: List of tool schemas in provider-agnostic format
            system_instruction: System prompt to guide the model
            json_mode: Whether to force JSON output
            **kwargs: Provider-specific options

        Returns:
            GenerationResult with text and/or tool calls
        """
        pass

    @abstractmethod
    def convert_tool_schema(self, tool: "Tool") -> Dict[str, Any]:
        """Convert a provider-agnostic tool to provider-specific format.

        Args:
            tool: A Tool instance from gentlebot.llm.tools

        Returns:
            Tool schema in the provider's expected format
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and identification."""
        pass

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for the given text.

        Default implementation uses character-based heuristic (~4 chars/token).
        Providers should override with their own tokenizers for accuracy.
        """
        if not text:
            return 0
        return max(1, len(text) // 4)


# Import Tool here to avoid circular imports, but make it available
# for type hints in convert_tool_schema
if False:  # TYPE_CHECKING equivalent that works at runtime
    from ..tools import Tool
