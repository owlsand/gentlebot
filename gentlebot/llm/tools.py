"""Provider-agnostic tool definitions.

This module defines tools in a format that can be converted to any
LLM provider's expected schema (Gemini, Claude, OpenAI).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolParameter:
    """Definition for a single tool parameter.

    Attributes:
        name: Parameter name
        type: JSON Schema type ("string", "integer", "boolean", "object", "array")
        description: Human-readable description of the parameter
        required: Whether the parameter is required
        enum: List of allowed values (for string parameters)
        minimum: Minimum value (for numeric parameters)
        maximum: Maximum value (for numeric parameters)
        default: Default value if not provided
    """
    name: str
    type: str
    description: str
    required: bool = True
    enum: Optional[List[str]] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    default: Any = None


@dataclass
class Tool:
    """Provider-agnostic tool definition.

    Tools are defined once and can be converted to any provider's format.

    Example:
        >>> tool = Tool(
        ...     name="calculate",
        ...     description="Evaluate a math expression",
        ...     parameters=[
        ...         ToolParameter("expression", "string", "The math expression")
        ...     ]
        ... )
        >>> gemini_schema = tool.to_gemini_schema()
        >>> openai_schema = tool.to_openai_schema()
    """
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)

    def _build_properties(self) -> tuple[Dict[str, Any], List[str]]:
        """Build JSON Schema properties and required list."""
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param in self.parameters:
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.minimum is not None:
                prop["minimum"] = param.minimum
            if param.maximum is not None:
                prop["maximum"] = param.maximum
            if param.default is not None:
                prop["default"] = param.default

            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        return properties, required

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to OpenAI/Claude function calling format.

        This format is used by OpenAI and Anthropic Claude.

        Returns:
            Tool schema in OpenAI function calling format
        """
        properties, required = self._build_properties()

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_gemini_schema(self) -> Dict[str, Any]:
        """Convert to Gemini function declaration format.

        Gemini uses a slightly different structure from OpenAI.

        Returns:
            Tool schema in Gemini function declaration format
        """
        properties, required = self._build_properties()

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def to_claude_schema(self) -> Dict[str, Any]:
        """Convert to Claude tool_use format.

        Claude's format is similar to OpenAI but has some differences.

        Returns:
            Tool schema in Claude tool_use format
        """
        properties, required = self._build_properties()

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


# ============================================================================
# Built-in Tool Definitions
# ============================================================================

WEB_SEARCH = Tool(
    name="web_search",
    description=(
        "Search the public web for up-to-date answers when local knowledge "
        "is insufficient. Use this for current events, recent information, "
        "or facts that may have changed since training."
    ),
    parameters=[
        ToolParameter(
            name="query",
            type="string",
            description="Keywords or question to search for",
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="Maximum number of results to return",
            required=False,
            minimum=1,
            maximum=5,
            default=3,
        ),
    ],
)

CALCULATE = Tool(
    name="calculate",
    description=(
        "Safely evaluate a math expression including arithmetic, percentages, "
        "and common functions (sqrt, log, sin, cos, tan, abs, round). "
        "Use this instead of estimating or calculating mentally."
    ),
    parameters=[
        ToolParameter(
            name="expression",
            type="string",
            description="Math expression such as '((42 * 1.08) - 5) / 3' or 'sqrt(144)'",
        ),
    ],
)

READ_FILE = Tool(
    name="read_file",
    description=(
        "Read a short snippet from a project file for citations or extra context. "
        "Files must be within the Gentlebot repository. Use for referencing code, "
        "configuration, or documentation."
    ),
    parameters=[
        ToolParameter(
            name="path",
            type="string",
            description="Relative path inside the repository to read",
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Maximum number of characters to return",
            required=False,
            minimum=100,
            maximum=4000,
            default=1200,
        ),
        ToolParameter(
            name="offset",
            type="integer",
            description="Character offset to start reading from",
            required=False,
            minimum=0,
            maximum=20_000,
            default=0,
        ),
    ],
)

IMAGE_GENERATION = Tool(
    name="generate_image",
    description=(
        "Generate an image based on a text prompt. Use this when a user asks "
        "you to create, draw, visualize, or make a picture of something. "
        "The generated image will be sent to the user."
    ),
    parameters=[
        ToolParameter(
            name="prompt",
            type="string",
            description="Detailed description of the image to generate",
        ),
    ],
)

# All available tools
ALL_TOOLS = [WEB_SEARCH, CALCULATE, READ_FILE, IMAGE_GENERATION]

# Tool lookup by name
TOOLS_BY_NAME: Dict[str, Tool] = {tool.name: tool for tool in ALL_TOOLS}


def get_tool(name: str) -> Tool | None:
    """Get a tool by name."""
    return TOOLS_BY_NAME.get(name)


def get_all_gemini_schemas() -> List[Dict[str, Any]]:
    """Get all tool schemas in Gemini format.

    Returns:
        List wrapped in function_declarations for Gemini API
    """
    return [{"function_declarations": [tool.to_gemini_schema() for tool in ALL_TOOLS]}]


def get_all_openai_schemas() -> List[Dict[str, Any]]:
    """Get all tool schemas in OpenAI format."""
    return [tool.to_openai_schema() for tool in ALL_TOOLS]


def get_all_claude_schemas() -> List[Dict[str, Any]]:
    """Get all tool schemas in Claude format."""
    return [tool.to_claude_schema() for tool in ALL_TOOLS]
