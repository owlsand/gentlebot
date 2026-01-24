"""Token estimation utilities for LLM providers.

This module provides token counting/estimation for different LLM providers.
Accurate token counting is important for staying within context limits
and estimating costs.
"""
from __future__ import annotations

from typing import Any, Dict, List


def estimate_tokens(text: str) -> int:
    """Estimate token count using character-based heuristic.

    Most modern LLMs (GPT, Claude, Gemini) use roughly 4 characters per token
    for English text. This is more accurate than word count, which varies
    wildly based on word length and punctuation.

    Args:
        text: The text to estimate tokens for

    Returns:
        Estimated token count (minimum 1 for non-empty text)

    Example:
        >>> estimate_tokens("Hello, world!")  # 13 chars
        3
        >>> estimate_tokens("")
        0
    """
    if not text:
        return 0
    # Roughly 4 characters per token for English text
    # This is a good approximation for Gemini, GPT-4, and Claude
    return max(1, len(text) // 4)


def estimate_tokens_for_messages(
    messages: List[Dict[str, Any]],
    system_instruction: str | None = None,
) -> int:
    """Estimate total tokens for a list of messages.

    Includes overhead for message formatting (role tags, separators).

    Args:
        messages: List of message dicts with "content" field
        system_instruction: Optional system prompt

    Returns:
        Estimated total token count
    """
    total = 0

    # System instruction
    if system_instruction:
        total += estimate_tokens(system_instruction)
        total += 4  # Overhead for system role marker

    # Messages
    for msg in messages:
        content = msg.get("content", "")
        total += estimate_tokens(content)
        total += 4  # Overhead for role marker and separators

    return total


def estimate_tokens_for_tool_calls(tool_calls: List[Dict[str, Any]]) -> int:
    """Estimate tokens for tool call formatting.

    Tool calls include the function name, arguments as JSON, and
    formatting overhead.

    Args:
        tool_calls: List of tool call dicts

    Returns:
        Estimated token count for tool calls
    """
    import json

    total = 0
    for call in tool_calls:
        name = call.get("name", "")
        args = call.get("args", {}) or call.get("arguments", {})

        total += estimate_tokens(name)
        total += estimate_tokens(json.dumps(args, default=str))
        total += 10  # Overhead for function call formatting

    return total


def truncate_to_token_budget(
    text: str,
    max_tokens: int,
    preserve_end: bool = False,
) -> str:
    """Truncate text to fit within a token budget.

    Args:
        text: Text to truncate
        max_tokens: Maximum tokens allowed
        preserve_end: If True, keep the end of the text instead of the start

    Returns:
        Truncated text that fits within the budget
    """
    if not text:
        return text

    estimated = estimate_tokens(text)
    if estimated <= max_tokens:
        return text

    # Calculate approximate character limit
    # Use 4 chars per token as our heuristic
    char_limit = max_tokens * 4

    if preserve_end:
        return text[-char_limit:]
    return text[:char_limit]


def split_by_token_budget(
    text: str,
    max_tokens_per_chunk: int,
) -> List[str]:
    """Split text into chunks that fit within token budgets.

    Tries to split on sentence boundaries when possible.

    Args:
        text: Text to split
        max_tokens_per_chunk: Maximum tokens per chunk

    Returns:
        List of text chunks
    """
    if not text:
        return []

    estimated = estimate_tokens(text)
    if estimated <= max_tokens_per_chunk:
        return [text]

    # Calculate approximate character limit per chunk
    char_limit = max_tokens_per_chunk * 4

    chunks: List[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= char_limit:
            chunks.append(remaining)
            break

        # Try to find a sentence boundary
        chunk = remaining[:char_limit]

        # Look for sentence-ending punctuation
        for punct in [". ", "! ", "? ", "\n\n", "\n"]:
            last_punct = chunk.rfind(punct)
            if last_punct > char_limit // 2:  # Don't split too early
                chunk = remaining[:last_punct + len(punct)]
                break

        chunks.append(chunk.strip())
        remaining = remaining[len(chunk):].strip()

    return chunks
