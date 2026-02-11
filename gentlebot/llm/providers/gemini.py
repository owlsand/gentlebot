"""Gemini LLM provider implementation.

This module provides the Gemini-specific implementation of the LLMProvider
interface, wrapping the google-genai SDK.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from types import SimpleNamespace

from .base import LLMProvider, Message, GenerationResult, ToolCall
from ...infra.retries import _extract_status

try:
    from google import genai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    class _DummyClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        class models:
            @staticmethod
            def generate_content(*a: Any, **k: Any) -> Any:
                raise RuntimeError("google-genai library not installed")

    class _DummyTypes:
        class GenerateContentConfig:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

        class ThinkingConfig:
            def __init__(self, *a: Any, **k: Any) -> None:
                pass

        class Part:
            @staticmethod
            def from_bytes(data: bytes, mime_type: str) -> bytes:
                return data

    genai = SimpleNamespace(Client=_DummyClient, types=_DummyTypes)  # type: ignore

log = logging.getLogger(f"gentlebot.{__name__}")


# Gemini accepts only ``user`` or ``model`` roles; map assistant messages to
# ``model`` and treat all others as ``user``.
ROLE_MAP = {"user": "user", "assistant": "model", "system": "user"}


class GeminiProvider(LLMProvider):
    """Gemini LLM provider implementing the abstract interface.

    This is the preferred way to use Gemini. It implements the LLMProvider
    interface for consistency with other providers.
    """

    def __init__(self, api_key: str | None) -> None:
        """Create a Gemini provider.

        Args:
            api_key: API key for Gemini. If not provided, a placeholder is used
                     but requests will fail.
        """
        if not api_key:
            log.warning("GEMINI_API_KEY not configured; using placeholder key")
            api_key = "test"
        else:
            log.debug("GEMINI_API_KEY provided (%d chars)", len(api_key))

        self.client = genai.Client(api_key=api_key)

    @property
    def name(self) -> str:
        """Provider name for logging."""
        return "gemini"

    def _convert_messages(self, messages: List[Message] | List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert messages to Gemini's expected format.

        Gemini expects messages as Content objects with parts containing text.
        """
        converted: List[Dict[str, Any]] = []
        for m in messages:
            if isinstance(m, Message):
                role = ROLE_MAP.get(m.role, "user")
                content = m.content
            else:
                role = ROLE_MAP.get(m.get("role", "user"), "user")
                content = m.get("content", "")
            converted.append({"role": role, "parts": [{"text": content}]})
        return converted

    def _extract_tool_calls(self, response: Any) -> List[ToolCall]:
        """Extract tool calls from Gemini response."""
        calls: List[ToolCall] = []
        for candidate in getattr(response, "candidates", []) or []:
            parts = getattr(getattr(candidate, "content", None), "parts", []) or []
            for i, part in enumerate(parts):
                func = getattr(part, "function_call", None)
                if not func and isinstance(part, dict):
                    func = part.get("function_call")
                if not func:
                    continue
                name = getattr(func, "name", None) or (func.get("name") if isinstance(func, dict) else None)
                if not name:
                    continue
                args = getattr(func, "args", None) or (func.get("args") if isinstance(func, dict) else None)
                calls.append(ToolCall(
                    id=f"call_{i}",
                    name=name,
                    arguments=args or {},
                ))
        return calls

    def convert_tool_schema(self, tool: Any) -> Dict[str, Any]:
        """Convert a Tool to Gemini's function declaration format."""
        # Import here to avoid circular imports
        from ..tools import Tool
        if isinstance(tool, Tool):
            return tool.to_gemini_schema()
        # Already in dict format
        return tool

    def generate(
        self,
        model: str,
        messages: List[Message] | List[Dict[str, Any]],
        temperature: float = 0.6,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        **kwargs: Any,
    ) -> GenerationResult:
        """Generate a completion from Gemini.

        Args:
            model: Gemini model name (e.g., "gemini-2.5-pro")
            messages: Conversation messages
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate (not used by Gemini directly)
            tools: Tool schemas in Gemini format
            system_instruction: System prompt
            json_mode: Force JSON output
            **kwargs: Additional options (thinking_budget supported)

        Returns:
            GenerationResult with text and/or tool calls
        """
        thinking_budget = kwargs.get("thinking_budget", 0)

        config = genai.types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
        )
        if json_mode:
            config.response_mime_type = "application/json"
        if thinking_budget:
            config.thinking = genai.types.ThinkingConfig(budget_tokens=thinking_budget)
        if tools:
            config.tools = tools

        content = self._convert_messages(messages)

        try:
            response = self.client.models.generate_content(
                model=model, contents=content, config=config
            )
        except Exception as exc:  # pragma: no cover
            status = _extract_status(exc)
            if status == 429:
                log.warning("Gemini rate-limited (429): %s", exc)
            else:
                log.exception("Gemini API call failed: %s", exc)
            raise

        # Extract text
        text = getattr(response, "text", "") or ""

        # Extract tool calls
        tool_calls = self._extract_tool_calls(response) if tools else []

        # Extract usage
        usage_meta = getattr(response, "usage_metadata", None)
        usage = None
        if usage_meta:
            usage = {
                "input_tokens": getattr(usage_meta, "prompt_token_count", 0),
                "output_tokens": getattr(usage_meta, "candidates_token_count", 0),
            }

        return GenerationResult(
            text=text,
            tool_calls=tool_calls,
            usage=usage,
            raw_response=response,
        )

    def generate_image(self, model: str, prompt: str, *images: bytes) -> Any:
        """Request an image from Gemini.

        Args:
            model: Image generation model
            prompt: Image generation prompt
            *images: Optional input images

        Returns:
            Raw Gemini response with image data
        """
        parts: List[Any] = [prompt]
        for img in images:
            parts.append(genai.types.Part.from_bytes(img, mime_type="image/png"))
        config = genai.types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"]
        )
        response = self.client.models.generate_content(
            model=model, contents=parts, config=config
        )
        return response


# Backward compatibility alias
class GeminiClient(GeminiProvider):
    """Legacy alias for GeminiProvider.

    Deprecated: Use GeminiProvider instead.
    """

    def generate(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float = 0.6,
        json_mode: bool = False,
        thinking_budget: int = 0,
        system_instruction: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Generate completion (legacy interface).

        Returns the raw Gemini response for backward compatibility.
        """
        result = super().generate(
            model=model,
            messages=messages,
            temperature=temperature,
            tools=tools,
            system_instruction=system_instruction,
            json_mode=json_mode,
            thinking_budget=thinking_budget,
        )
        # Return raw response for backward compatibility
        return result.raw_response
